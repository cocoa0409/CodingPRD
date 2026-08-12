# Duty Drawback & Tariff Classification API — Product Requirements Document

## 1. Introduction

Customs consulting firms that specialize in duty drawback operate under an unusual combination of pressures: a statutory five-year window to file for recovery of duties already paid, an evidentiary burden that obliges the firm to retain supporting documentation for three years after any recovery, a segregation-of-duties discipline that separates the preparer of a filing from the licensed broker who signs it, and a revenue model — contingency billing — that makes the firm's own fee a direct function of the amounts actually recovered from U.S. Customs and Border Protection (CBP). A miscoded Harmonized Tariff Schedule (HTS) line, an overlooked Section 301 exclusion, or a substitution claim that overruns the export shipment's FOB value is not merely an accounting slip; it is potential negligence exposure in a subsequent CBP audit.

This document specifies the Duty Drawback & Tariff Classification API, a system that a customs consulting firm uses to run the full engagement lifecycle: onboarding importer and exporter clients, classifying their products under the HTS with optional first-sale valuation analysis, pursuing binding rulings from CBP where classification is contested, registering import entries and export shipments, matching them into drawback claims under either direct-identification or substitution methodology, filing those claims and shepherding them through CBP review cycles, billing recovered duties on contingency, and defending the work in subsequent audits — all while honoring statutory filing deadlines and recordkeeping-retention obligations. All endpoints are mounted under the `/customs` prefix.

The system keeps its own logical clock rather than trusting wall-clock time, because statutory deadlines and retention windows must be testable and reproducible. Every system-stamped timestamp — filing time, payment time, sweep comparisons, deadline checks — reads from this logical clock. Before any operator explicitly sets it, the logical clock reads exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID` identifies the acting individual or client, and `X-User-Role` declares the capacity in which they act. The system recognizes five roles, spelled exactly as follows: `FirmAdmin`, `Analyst`, `LicensedBroker`, `ComplianceManager`, and `ClientContact`. A request that omits either header, or that presents a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

For the roles `FirmAdmin`, `Analyst`, `LicensedBroker`, and `ComplianceManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow requires attribution — for example as `submitted_by_user_id`, `certified_by_user_id`, `prepared_by_user_id`, or `filed_by_user_id` — but never compares it to any entity's `id`. When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's `client_id` field to `X-User-ID`, and a `ClientContact` attempting to read another client's resource or respond to a deficiency on another client's claim is rejected with `ERR_FORBIDDEN`.

Two operations in the system are segregated so that the same individual cannot perform both sides of a control pair. Filing a drawback claim must be performed by a different `X-User-ID` than the one captured as the claim's `prepared_by_user_id`, and certifying a classification must be performed by a different `X-User-ID` than the one captured as the classification's `submitted_by_user_id`. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.
- The same error envelope covers routing and server failures: a request to an unknown path, or to a known path with an unsupported method, surfaces `ERR_NOT_FOUND` (HTTP 404); an unexpected server failure surfaces `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, accepts a minimum of 1, and is capped at 100. Both parameters must be integers: a non-integer `limit` or `offset`, a `limit` below 1, or an `offset` below 0 is rejected with `ERR_INVALID_REQUEST`, while a `limit` above 100 is silently clamped to 100 rather than rejected. The `offset` parameter sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by insertion order (resources created earlier sort first). Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Money, Rates, and Rounding Discipline

All monetary amounts in the system are integer cents — never fractional dollars, never floating point. All percentage rates (duty rates, surcharge rates, contingency fees, culpability rates, the refund rate) are integer basis points, where 10000 basis points equals one hundred percent; a contingency fee of 2500 basis points therefore represents a 25.00% fee. Every rounding in the system is round half up to integer cents, applied at precisely the step each calculation specifies — and several calculations deliberately pin a per-component rounding followed by an integer sum, because rounding a grand total instead would produce a different cent figure. The drawback refund rate is 99% of eligible duty, expressed as 9900 basis points.

### 2.5. Common Resource Properties

Every primary resource carries a standard system-managed field set. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp is an ISO 8601 UTC value with three fractional digits recorded at creation. The `updated_at` timestamp follows the same format and refreshes on every mutation. Both `created_at` and `updated_at` are stamped from wall-clock UTC; the logical clock of §2.8 governs only business timestamps and comparisons — `filed_at`, `paid_at`, filing deadlines, retention windows, measure effective windows, and audit due dates. The `version` is an integer that starts at 1 on creation and increments by one on every mutation of the resource — including mutations driven by cross-entity cascades, so a single client-visible operation may advance the versions of several resources at once.

### 2.6. Optimistic Concurrency Control

Three write endpoints in the system require an explicit optimistic-concurrency field, and no other endpoint accepts one. Updating a draft claim's period or type requires the request to carry `expected_claim_version` equal to the claim's current `version`. Posting a correction to an import entry requires `expected_import_entry_version` equal to the entry's current `version`. Superseding a classification requires `expected_classification_version` equal to the classification's current `version`. In each case, if the supplied value does not match the resource's current `version` — because another write has advanced the resource since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from silently overwriting state it has not observed. Endpoints not named here do not take a version field; their ordering is arbitrated by state preconditions alone.

### 2.7. Validation Ordering

When a request fails for more than one reason, the system reports the earliest failure in a fixed priority order rather than an arbitrary one. Authentication comes first: missing or malformed headers surface `ERR_UNAUTHENTICATED` before anything else is examined. Authorization follows, so a role violation surfaces `ERR_FORBIDDEN` before the server inspects the path. Path-template identifiers are then resolved left to right, with the first nonexistent identifier producing `ERR_NOT_FOUND`. Only after the target is located does the server check body shape — and each identifier referenced by a body field (such as `client_id`, `classification_id`, `import_entry_id`, or `export_shipment_id`) is resolved immediately after its own field passes shape validation and before any stale-version or state-machine check, a nonexistent body-referenced identifier likewise producing `ERR_NOT_FOUND`. Body shape is checked — missing required fields, invalid enum values, non-positive integers, or a missing required optimistic-concurrency field — as `ERR_INVALID_REQUEST`. Stale-version checks come next (`ERR_STALE_VERSION`), then state-machine legality (`ERR_INVALID_STATE` for a resource not in a valid from-state, `ERR_ALREADY_TERMINAL` for one already terminal), then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then cross-entity referential rules (classification certification, client engagement, same-client references), then temporal rules (windows, filing deadlines, audit due dates), then uniqueness and overlap rules (entry numbers, measure windows, claim periods, deficiency limits), then match compatibility and quantity bounds, then frozen-ledger protections, and finally fiscal caps such as the export value pool and the various payment equalities. A consequence worth internalizing: a request that is both unauthenticated and aimed at a nonexistent resource always surfaces the authentication error.

### 2.8. The Logical Clock and the Ops Sweep

The server's logical clock governs every time-sensitive rule: the five-year statutory filing window, the three-year retention window, tariff-measure effective windows, and audit response deadlines. A firm administrator may set the clock to an arbitrary instant by supplying `to_iso8601` to the test-driving clock endpoint, and the clock thereafter reads exactly that value until set again; the endpoint responds with an object whose `current_utc` field echoes the new logical-clock value.

Two families of resources age out through an explicit ops sweep rather than continuously. Running the sweep transitions every `ACTIVE` tariff measure whose `effective_to` is set and is less than or equal to the logical clock — the comparison is inclusive at the exact expiry second — into `EXPIRED`, and transitions every compliance record whose `retention_until` is set and is less than or equal to the logical clock, also inclusive, from `RETAINED` to `ELIGIBLE_FOR_DESTRUCTION`. The sweep response names what it touched as `expired_measure_ids` and `eligible_record_ids`. Every measure expiry triggers a recomputation of the eligible-duty figures on matching import entries, exactly as a manual revocation would; an entry matched by several measures expiring in the same sweep is recomputed once, with a single `version` increment.

### 2.9. Frozen Ledgers and Compensation Cascades

Once a drawback claim leaves `DRAFT`, the lines beneath it become part of a filed federal submission, and the system treats them as frozen. Two protections follow. An import entry referenced by any `ACTIVE` claim line belonging to a claim that is not in `DRAFT` cannot be corrected; the attempt is rejected with `ERR_ENTRY_LOCKED_BY_FILED_CLAIM`. And a new tariff measure whose window would reduce the eligible duty of an entry already referenced by `ACTIVE` claim lines cannot be published; the attempt is rejected with `ERR_MEASURE_BLOCKED_BY_CLAIM_LINES`. Revoking or expiring a measure never runs afoul of this protection, because removing a surcharge only ever increases eligible duty, never shrinks it.

Whenever a claim line is voided — whether individually while the claim is still a draft, or wholesale because the claim was denied or cancelled — the system runs a compensation cascade that restores the matched pools: the import entry's consumed quantity and unclaimed-duty figure are restored, the export shipment's consumed quantity and remaining value pool are restored, and every resource the cascade touches has its `updated_at` refreshed and its `version` incremented. This cascade is what allows a denied claim's merchandise to become matchable again under a fresh claim.

## 3. Business Logic & Workflows

### 3.1. Client Engagement

A `FirmAdmin` onboards each importer or exporter as a `Client` by supplying the legal `name`, the IRS-issued `importer_of_record_number` — which must be globally unique across all clients, a collision rejected with `ERR_INVALID_REQUEST` — and the engagement's `contingency_fee_bps`, the firm's percentage cut of any recovered duty expressed in basis points. The fee must be greater than zero and no more than 10000 basis points, a violation rejected with `ERR_INVALID_REQUEST`; the firm never works for free and never takes more than the entire recovery. A new client begins in `engagement_status` `ACTIVE` with its aggregates zeroed: `lifetime_recovered_cents` at zero, `projected_fee_accrual_cents` at zero, and `open_audit_count` at zero.

Engagement status is a lifecycle of its own, managed by a `FirmAdmin`. From `ACTIVE`, a client may be placed into `SUSPENDED`, and from `SUSPENDED` it may be reactivated to `ACTIVE`. Termination is reachable from either `ACTIVE` or `SUSPENDED`, and `TERMINATED` is terminal — no further transitions are possible, and any attempt is rejected with `ERR_ALREADY_TERMINAL`. While a client is in `SUSPENDED` or `TERMINATED`, two operations against that client are blocked with `ERR_CLIENT_NOT_ACTIVE`: creating a new drawback claim, and filing an existing one. Every status change increments the client's `version`.

The three client aggregates are recomputed as the business moves. `lifetime_recovered_cents` is the sum of `paid_duty_cents` over the client's claims that have reached `PAID`. `open_audit_count` is the number of the client's audit cases currently in `OPENED`, `EVIDENCE_GATHERING`, or `RESPONSE_FILED`. `projected_fee_accrual_cents` is the firm's accrued revenue projection: for each of the client's claims currently in `APPROVED`, the approved amount is first subjected to an 80% realization haircut — that is, multiplied by 8000 basis points and rounded half up to integer cents — and the result is then passed through the tiered fee schedule described in §3.7 at the client's current `contingency_fee_bps`. Because of the haircut, an identical approved-and-paid amount yields a lower accrual than the settled fee eventually invoiced.

### 3.2. Classification, First-Sale Valuation, and Binding Rulings

Before any drawback can be computed, the merchandise must be classified. An `Analyst` creates an `HTSClassification` for a client by supplying `client_id`, the client's `product_sku`, the ten-digit `hts_code`, the `country_of_origin`, the general `duty_rate_bps`, and the `declared_unit_value_cents` — the transaction (last-sale) unit value declared at entry. `duty_rate_bps` must be zero or positive and `declared_unit_value_cents` must be at least one, violations rejected with `ERR_INVALID_REQUEST`. The classification is born in `DRAFT` status with `version` 1.

Three optional booleans and one optional price govern the first-sale valuation analysis, a technique for lowering the dutiable value when goods pass through a middleman. The analyst records `bona_fide_sale` (there was a bona fide sale between the factory and the middleman), `arms_length` (the factory-to-middleman transaction was at arm's length), and `clearly_destined_us` (the goods were clearly destined for the United States at the time of the first sale), each defaulting to `false`, plus `first_sale_price_cents`, the factory's unit price, defaulting to null and required to be at least one when present (`ERR_INVALID_REQUEST` otherwise). The system derives `first_sale_eligible`, which is true exactly when all three booleans are true and `first_sale_price_cents` is present and strictly less than `declared_unit_value_cents`. From that it derives `appraised_unit_value_cents`: the first-sale price when eligible, otherwise the declared unit value.

Classification follows a rework loop with segregation of duties. The analyst who drafted the classification submits it for review, moving it `DRAFT → IN_REVIEW`; the system stamps `submitted_by_user_id` with the submitter's `X-User-ID`. A `LicensedBroker` then renders a review decision. A `decision` of `REWORK` returns the classification to `DRAFT` without clearing `submitted_by_user_id` — a later re-submission overwrites it — and the cycle from `DRAFT` to `IN_REVIEW` and back may repeat indefinitely. A `decision` of `CERTIFY` moves it to `CERTIFIED` and stamps `certified_by_user_id` — but only if the certifying broker is not the same individual who submitted it; a self-certification is rejected with `ERR_SEGREGATION_OF_DUTIES`. Each transition bumps the classification's `version`.

A certified classification is not immutable. When trade facts change, an `Analyst` supersedes it: the request carries the successor's classification fields — `product_sku`, `hts_code`, `country_of_origin`, `duty_rate_bps`, `declared_unit_value_cents`, and optionally `first_sale_price_cents`, `bona_fide_sale`, `arms_length`, and `clearly_destined_us` — together with `expected_classification_version` as described in §2.6. A stale version is rejected with `ERR_STALE_VERSION`. On success, the existing classification transitions `CERTIFIED → SUPERSEDED` (its terminal state) with its `version` incremented, and a brand-new classification is created in `DRAFT` carrying the payload's fields and a `supersedes_id` pointing back at the superseded record; `supersedes_id` is null on any classification not born of a supersede. The response is `201 Created` carrying the newly created successor classification, not the superseded record. Supersession is the only operation that sets `supersedes_id`, and only a `CERTIFIED` classification may be superseded — attempting it from any other state is `ERR_INVALID_STATE`.

Where classification itself is contested, a `LicensedBroker` may file a `BindingRuling` request against a `CERTIFIED` classification — referencing a classification in any other status is rejected with `ERR_CLASSIFICATION_NOT_CERTIFIED`. The request names the `classification_id` and the `requested_hts_code` the firm believes correct, and the ruling is created directly in `SUBMITTED`. When CBP answers, the broker records the outcome. An `outcome` of `DENIED` or of `WITHDRAWN` simply transitions the ruling to that terminal state and increments its `version`. An `outcome` of `ISSUED` requires both `issued_hts_code` and `issued_duty_rate_bps` to be present — their absence is `ERR_INVALID_REQUEST` — and does considerably more: the ruling becomes `ISSUED`, and the linked classification is re-rated in place, its `hts_code` overwritten with `issued_hts_code`, its `duty_rate_bps` overwritten with `issued_duty_rate_bps`, and its `version` incremented. An issued ruling therefore changes the duty arithmetic for everything classified under that record going forward.

### 3.3. Import Entries, Export Shipments, and Tariff Measures

With a certified classification in hand, an `Analyst` registers the client's trade data. An `ImportEntry` is created with `client_id`, the `classification_id` it was entered under — which must reference a `CERTIFIED` classification belonging to the same client, otherwise `ERR_CLASSIFICATION_NOT_CERTIFIED` or `ERR_CROSS_CLIENT_REFERENCE` respectively — the CBP `entry_number`, which must be unique within the client (`ERR_DUPLICATE_ENTRY_NUMBER` on collision), the `entry_date` that anchors the five-year statutory filing clock, the `port_code`, the `line_quantity` of units (which must be positive), the `entered_value_cents`, and the `duty_paid_cents` actually paid including any trade-remedy surcharges (`entered_value_cents` and `duty_paid_cents` must be zero or positive, `ERR_INVALID_REQUEST` otherwise). An entry carries no `hts_code` field of its own: wherever this document speaks of an entry's HTS code — measure-prefix matching below, the direct-match equality of §3.4 — it means the current `hts_code` of the entry's referenced classification, which an issued binding ruling may re-rate in place. An `ExportShipment` is created with `client_id`, `export_date`, the exported article's `hts_code`, the `quantity` exported (positive), the `fob_value_cents` that caps how much drawback can ever be recovered against the shipment (zero or positive), the `dest_country`, and `substituted_duty_rate_bps` — the duty rate that would have applied to the exported article had it been imported, which feeds the lesser-of rule for substitution claims. This substitute-side rate must be zero or positive but carries no upper bound: values above 10000 basis points — a notional duty rate over 100% — are valid input. Both resources track a system-maintained `matched_quantity` counting units consumed by `ACTIVE` claim lines, and both derive a `status` from the same bands: `UNMATCHED` when `matched_quantity` is zero, `PARTIALLY_MATCHED` when it is greater than zero but below the total quantity, and `MATCHED` once it reaches the entry's `line_quantity` or the shipment's `quantity` respectively. These status transitions are system-driven side effects of line creation and voiding, never direct client operations: a line becoming `ACTIVE` with partial consumption moves the target from `UNMATCHED` to `PARTIALLY_MATCHED`, full consumption moves it to `MATCHED`, voiding a line from `MATCHED` drops it back to `PARTIALLY_MATCHED`, and voiding the last referencing line returns it to `UNMATCHED`.

Not every dollar of duty paid is recoverable. Trade-remedy surcharges — Section 301 duties, antidumping and countervailing duties, safeguard duties — are excluded from drawback. A `FirmAdmin` publishes these as `TariffMeasure` records, each carrying an `hts_code_prefix` matched by prefix against entry HTS codes, a `measure_type` of `EXCLUSION`, `SECTION_301`, `AD_CVD`, or `SAFEGUARD`, a `surcharge_bps` rate (zero or positive, `ERR_INVALID_REQUEST` otherwise) applied to the entry's entered value (the rate is ignored for `EXCLUSION` measures, which instead neutralize Section 301), and an effective window from `effective_from` to `effective_to`. The window is half-open: a measure covers an entry whose `entry_date` is at or after `effective_from` and strictly before `effective_to`, and a null `effective_to` means the measure is open-ended. Creating a measure requires `effective_to`, when present, to be strictly after `effective_from` (`ERR_INVALID_WINDOW` otherwise). Two `ACTIVE` measures sharing the same `measure_type` and `hts_code_prefix` may not have overlapping half-open windows, though adjacency — one measure's `effective_to` landing exactly on the other's `effective_from` — is allowed; overlaps are rejected with `ERR_MEASURE_WINDOW_OVERLAP`. A new measure is also rejected with `ERR_MEASURE_BLOCKED_BY_CLAIM_LINES` if its window would reduce the eligible duty of any entry already referenced by `ACTIVE` claim lines.

Every entry's drawback economics derive from these measures through a pinned computation. The system collects all `ACTIVE` measures whose prefix the entry's `hts_code` starts with and whose half-open window covers the `entry_date`. For each matching measure it computes a per-measure non-drawbackable amount, rounded half up to integer cents individually and then summed into the entry's `non_drawbackable_cents`: an `EXCLUSION` measure contributes zero; a `SECTION_301` measure contributes zero whenever any matching `EXCLUSION` is also present (the exclusion neutralizes it); every other matching measure contributes the entered value multiplied by its `surcharge_bps` and divided by 10000, rounded half up. The entry's `drawback_eligible_duty_cents` is then the greater of zero or `duty_paid_cents` minus `non_drawbackable_cents`, and its `unclaimed_duty_cents` is the eligible duty minus the sum of `drawback_amount_cents` over all `ACTIVE` claim lines referencing it. Symmetrically, each shipment's `value_pool_remaining_cents` is its `fob_value_cents` minus the sum of `drawback_amount_cents` over `ACTIVE` lines referencing it. These derived figures are recomputed on entry creation, on entry correction, on measure creation, on measure revocation, and when the ops sweep expires a measure — and every recomputation increments the touched entry's `version`. A `FirmAdmin` may also revoke an `ACTIVE` measure outright; the measure becomes `REVOKED`, and matching entries are recomputed in the same way, with revocation only ever removing surcharges and therefore never shrinking eligible duty. `REVOKED` and `EXPIRED` are both terminal for a measure; attempting to revoke a measure not in `ACTIVE` is rejected with `ERR_ALREADY_TERMINAL`.

### 3.4. Building and Filing a Drawback Claim

An `Analyst` opens a `DrawbackClaim` for a client by supplying `client_id`, a `claim_type` of `DIRECT_IDENTIFICATION` or `SUBSTITUTION`, and a coverage window from `period_start` to `period_end`. The period is a closed interval — both bounds inclusive — and `period_end` must be on or after `period_start` (`ERR_INVALID_WINDOW` otherwise). The client must be `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE` otherwise), and the new claim's period must not overlap the period of any other claim of the same client and same `claim_type` that is not in a terminal state; because periods are closed intervals, two claims that share even a single date are overlapping (`ERR_CLAIM_PERIOD_OVERLAP`), while genuinely back-to-back periods are allowed. The claim is created in `DRAFT` with `prepared_by_user_id` stamped from the analyst's `X-User-ID`, `deficiency_count` at zero, `estimate_cents` at zero, and `claimed_duty_cents`, `approved_duty_cents`, `paid_duty_cents`, `filed_at`, `paid_at`, and `filing_deadline` all null. While the claim remains in `DRAFT`, the analyst may replace its `period_start`, `period_end`, or `claim_type`; any of the three may be omitted from the request, in which case the current value is retained. The update requires `expected_claim_version` per §2.6 and re-validates both the closed-window rule (`period_end` on or after `period_start`, `ERR_INVALID_WINDOW` on violation) and the period-overlap rule against the merged new values, excluding the claim itself from the overlap scan.

The substance of a claim is its `ClaimLine` records, each matching some units of one import entry against one export shipment. Adding a line to a `DRAFT` claim requires `import_entry_id`, `export_shipment_id`, and a positive `matched_quantity`, and both referenced resources must belong to the same client as the claim (`ERR_CROSS_CLIENT_REFERENCE` otherwise). The line's `match_method` is copied from the claim's `claim_type` at creation as `DIRECT` or `SUBSTITUTION` and never changes thereafter. Quantity is bounded by availability on both sides: `matched_quantity` may not exceed the entry's remaining unmatched units or the shipment's remaining unmatched units, and a violation is `ERR_MATCH_QUANTITY_EXCEEDED`. Under `DIRECT_IDENTIFICATION`, the exported article must be the very same kind of merchandise that was imported, so the shipment's `hts_code` must equal the entry's `hts_code` — a mismatch is `ERR_MATCH_INCOMPATIBLE`. Under `SUBSTITUTION`, different but substitutable merchandise may be matched, and no such HTS equality is required.

The line's `drawback_amount_cents` — the refund attributable to this match — is computed differently per methodology, always rounded half up to integer cents. Under direct identification, the entry's current `drawback_eligible_duty_cents` is divided by its `line_quantity` as an exact rational to obtain a per-unit eligible duty; that unit figure is multiplied by 9900 basis points (the 99% refund rate) and by the line's `matched_quantity`, and the result is rounded half up. Under substitution, the lesser-of rule of 19 U.S.C. §1313(l) applies: the import side's per-unit eligible duty is computed the same way, while the substitute side's per-unit duty is the shipment's `substituted_duty_rate_bps` multiplied by its `fob_value_cents` and divided by the product of 10000 and the shipment's `quantity`, again as an exact rational; the refund base is whichever per-unit figure is smaller, multiplied by 9900 basis points and by `matched_quantity`, rounded half up. Substitution lines carry one further guard: the raw refund must not exceed the shipment's current `value_pool_remaining_cents`, the FOB pool cap, and an overrun is rejected with `ERR_EXPORT_VALUE_POOL_EXCEEDED`. There is no corresponding pool cap on the entry side — the per-unit arithmetic makes overdrawing an entry mathematically unreachable.

Pool consumption across competing lines follows a pinned chronological order: decrements apply in ascending `created_at` order of the claim lines, tie-broken by global insertion order (a monotonic creation sequence), so that a later line always observes pool balances net of every earlier `ACTIVE` line. Random identifier ordering is explicitly forbidden as a tie-break.

Creating a line mutates three resources beyond the line itself: the entry's `matched_quantity` and `unclaimed_duty_cents` absorb the consumption, the shipment's `matched_quantity` and `value_pool_remaining_cents` do likewise, and the claim's `estimate_cents` is recomputed — with `version` incremented on every touched resource and entry/export status bands re-evaluated. Voiding a line — permitted only while the parent claim is in `DRAFT`, rejected with `ERR_INVALID_STATE` when the claim is in any non-`DRAFT` non-terminal state and with `ERR_ALREADY_TERMINAL` when the claim is already terminal, and rejected with `ERR_ALREADY_TERMINAL` against an already `VOID` line — flips the line to its terminal `VOID` status and runs the compensation cascade of §2.9 in reverse: the entry's unclaimed duty and matched quantity are restored, the shipment's pool and matched quantity are restored, and the claim's estimate is recomputed, again with version increments throughout.

While the claim is in `DRAFT`, its `estimate_cents` is a provisional figure: every line addition, line void, or correction to a referenced entry re-evaluates every `ACTIVE` line's refund formula live against the entry's current eligible-duty fields and re-sums the claim total. Filing freezes everything. When a `LicensedBroker` files the claim, four preconditions hold: the client must still be `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`); the claim must have at least one `ACTIVE` line (`ERR_INVALID_REQUEST`); the broker's `X-User-ID` must differ from `prepared_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); and the logical clock must not have passed the claim's `filing_deadline` (`ERR_FILING_DEADLINE_PASSED`). The deadline itself is statutory: five years after the earliest `entry_date` among the entries referenced by the claim's `ACTIVE` lines, and the comparison is inclusive — filing at the exact deadline second is still permitted. The `filing_deadline` field is maintained continuously while the claim is a draft: it is recomputed on every line addition and every line void, and it is null whenever the claim has no `ACTIVE` lines. On filing, the claim transitions `DRAFT → FILED`, `filed_at` and `filed_by_user_id` are stamped, and `claimed_duty_cents` is frozen as the sum of the then-current per-line `drawback_amount_cents` values. The aggregation order is pinned: each line is first rounded half up to integer cents, and those integers are then summed. Summing raw unrounded values and rounding once at the end is forbidden — two lines whose raw refunds are each a half-cent value must contribute two rounded cents to the total, not lose both halves to a single final rounding. From `FILED` onward the estimate is never recomputed and entry corrections against the claim's entries are locked per §2.9. Filing also auto-creates the claim's evidentiary package: three `ComplianceRecord` resources with `doc_type` `ENTRY_DOCS`, `EXPORT_PROOF`, and `MATCHING_WORKSHEET`, each in `RETAINED` status with `retention_until` still null, because the three-year retention clock has not yet started.

### 3.5. CBP Review, Deficiency Cycles, and Payment

A filed claim waits on CBP. A `LicensedBroker` records the agency's review outcome, and the `FILED` state branches three ways. An `outcome` of `APPROVED` requires `approved_duty_cents` to be present and no greater than the frozen `claimed_duty_cents` — CBP may allow less than was claimed but never more, and an excess is `ERR_APPROVED_EXCEEDS_CLAIMED`. The approved amount is recorded, the claim becomes `APPROVED`, and the client's `projected_fee_accrual_cents` is recomputed because the claim has entered the accrual set. An `outcome` of `DENIED` transitions the claim to its terminal `DENIED` state and voids every `ACTIVE` line with the full pool-and-quantity restoration cascade, freeing the merchandise for future claims. An `outcome` of `DEFICIENCY` is CBP's request for more information; it is available only while the claim's `deficiency_count` is below two — a third deficiency attempt is rejected with `ERR_DEFICIENCY_LIMIT_REACHED` — and it moves the claim to `DEFICIENCY_ISSUED` while incrementing `deficiency_count`.

The deficiency cycle is a loop: from `DEFICIENCY_ISSUED`, an `Analyst`, a `LicensedBroker`, or the client's own `ClientContact` may file the deficiency response, returning the claim to `FILED` for another review round. The cycle from `FILED` to `DEFICIENCY_ISSUED` and back may occur at most twice over the claim's life, as bounded by the deficiency counter. From `DEFICIENCY_ISSUED` no direct transition to `APPROVED` or `DENIED` exists; the claim must pass back through `FILED`.

Once `APPROVED`, a `FirmAdmin` records receipt of the recovered funds. The `paid_duty_cents` supplied must equal `approved_duty_cents` exactly — partial recoveries are not modeled, and a mismatch is `ERR_PAID_AMOUNT_MISMATCH`. Payment is a three-link cascade. First, the claim transitions `APPROVED → PAID` with `paid_at` stamped from the logical clock. Second, an `Invoice` is auto-created in `ISSUED` status with its `claim_id` and `client_id` copied from the claim, `recovered_duty_cents` snapshotting `paid_duty_cents`, `fee_bps_snapshot` capturing the client's `contingency_fee_bps` at that instant — so a later fee renegotiation never reopens a settled invoice — and `fee_cents` computed per the settled tiered schedule of §3.7. Third, the client's aggregates move: `lifetime_recovered_cents` grows by `paid_duty_cents`, `projected_fee_accrual_cents` is recomputed because the claim has left the `APPROVED` accrual set, and the client's `version` increments. In the same act, the claim's three compliance records each receive `retention_until` set to `paid_at` plus three years, with each record's `version` incremented — the statutory retention clock starts ticking at payment, not before.

A claim still in `DRAFT` may instead be abandoned: an `Analyst` cancels it, the claim becomes `CANCELLED`, and every `ACTIVE` line is voided with the same compensation cascade as a denial. `PAID`, `DENIED`, and `CANCELLED` are all terminal; any further transition attempt against them is `ERR_ALREADY_TERMINAL`.

### 3.6. Correcting Import Entries Under Optimistic Concurrency

Trade data is not static — CBP liquidations and post-entry amendments change the figures. An `Analyst` may post a correction to an import entry carrying any of `duty_paid_cents`, `entered_value_cents`, or `line_quantity`, together with the mandatory `expected_import_entry_version` of §2.6. Two guards protect downstream math. The corrected `line_quantity` may not drop below the entry's current `matched_quantity` — units already matched into claims cannot be corrected out of existence (`ERR_MATCH_QUANTITY_EXCEEDED`). And per §2.9, the entry must not be referenced by any `ACTIVE` line of a claim outside `DRAFT`, or the correction is `ERR_ENTRY_LOCKED_BY_FILED_CLAIM`.

A successful correction is itself a three-link cascade. The entry's own fields are updated and its eligible-duty figures — `non_drawbackable_cents`, `drawback_eligible_duty_cents`, `unclaimed_duty_cents` — are recomputed against the active measures. Then every `ACTIVE` claim line referencing the entry that belongs to a claim still in `DRAFT` has its `drawback_amount_cents` re-evaluated against the new entry figures. Finally, each affected draft claim's `estimate_cents` is recomputed. Every entity the cascade touches — entry, lines, claims — has its `version` incremented. Lines under filed claims are untouched by design: a filed claim's frozen `claimed_duty_cents` never moves.

### 3.7. Contingency-Fee Billing

The firm's revenue is a percentage of what it recovers, computed on a two-tier schedule that rewards large recoveries with a discounted marginal rate. For any recovered amount and fee rate, the tiered fee is: the first tier base is the lesser of the recovered amount and 1000000 cents — that is, the first ten thousand dollars; the second tier base is whatever remains above that threshold, or zero if none does; the first tier's fee is the first tier base multiplied by the fee rate in basis points and divided by 10000, rounded half up to integer cents; the second tier's fee is the second tier base multiplied by the fee rate and by 8000 basis points — the rate after a 2000-basis-point marginal discount, i.e. the second tier bills at 80% of the agreed rate — divided by 100000000, also rounded half up; and the invoice fee is the integer sum of the two rounded tier fees. Each tier is rounded independently before summing; rounding only the combined fee is forbidden.

This schedule runs in two variants. The settled variant fires once, at invoice creation on claim payment: the recovered amount is the claim's `paid_duty_cents` and the rate is the invoice's `fee_bps_snapshot`. The accrued variant drives the client's `projected_fee_accrual_cents` while claims sit in `APPROVED`: the recovered amount for each such claim is its `approved_duty_cents` multiplied by 8000 basis points and divided by 10000 — the 80% realization haircut reflecting that approved amounts are not yet cash — rounded half up, and the rate is the client's current `contingency_fee_bps`.

An invoice's `balance_cents` is its `fee_cents` minus accumulated `amount_paid_cents`, which starts at zero. A `FirmAdmin` records client payments against it; each `amount_cents` must be positive and may not exceed the current `balance_cents` (`ERR_PAYMENT_EXCEEDS_BALANCE`). A payment smaller than the balance moves the invoice `ISSUED → PARTIALLY_PAID` (or keeps it in `PARTIALLY_PAID`), while a payment exactly equal to the balance — the exact-equality boundary — settles it to `PAID`. Each payment adds to `amount_paid_cents` and increments the invoice's `version`. A `ComplianceManager` may void an invoice, but only while no payment has ever been recorded against it — `amount_paid_cents` must be zero, otherwise `ERR_INVOICE_HAS_PAYMENTS` — moving it from `ISSUED` to the terminal `VOID`. Both `PAID` and `VOID` are terminal.

### 3.8. Audit Defense and Penalty Exposure

CBP audits drawback claimants aggressively, and the system tracks each engagement as an `AuditCase`. A `FirmAdmin` opens a case against a client with an `opened_reason` of `CF28` (a CBP Form 28 request for information), `FOCUSED_ASSESSMENT`, or `POST_PAYMENT_AUDIT`, plus a `due_date` for the firm's response and an optional `claim_id` restricting the audit's scope to a single claim — a `claim_id` that does not exist is `ERR_NOT_FOUND`, and one belonging to a different client is `ERR_CROSS_CLIENT_REFERENCE`. The case opens in `OPENED` with `culpability_level` null and `penalty_exposure_cents` at zero, and the client's `open_audit_count` is recomputed.

A `ComplianceManager` advances the case through its workflow by naming an `action`. From `OPENED`, `START_EVIDENCE` moves the case to `EVIDENCE_GATHERING` and recomputes the client's open-audit count. From `EVIDENCE_GATHERING`, `FILE_RESPONSE` moves it to `RESPONSE_FILED` — but only if the logical clock has not passed `due_date`; the deadline is inclusive, so a response at the exact due second is permitted, and a later attempt is `ERR_RESPONSE_PAST_DUE`. Auditors frequently come back with follow-up questions: from `RESPONSE_FILED`, `REQUEST_MORE` returns the case to `EVIDENCE_GATHERING`, and this follow-up cycle may repeat indefinitely. Closure happens only from `RESPONSE_FILED`. `CLOSE_REFUTED` — the firm successfully defended the claim — moves the case to `CLOSED_REFUTED` and recomputes the client's open-audit count. `CLOSE_SUSTAINED` — CBP's finding stood — requires a `culpability_level` of `NONE`, `NEGLIGENCE`, `GROSS_NEGLIGENCE`, or `FRAUD` (its absence is `ERR_INVALID_REQUEST`) and computes the firm's `penalty_exposure_cents`: the scope total is the linked claim's `paid_duty_cents` when `claim_id` is set and that claim is `PAID`, otherwise the sum of `paid_duty_cents` over all of the client's `PAID` claims; the applicable rate is 0 basis points for `NONE`, 500 for `NEGLIGENCE`, 2000 for `GROSS_NEGLIGENCE`, and 10000 for `FRAUD`; and the exposure is the scope total multiplied by that rate and divided by 10000, rounded half up to integer cents. The client's `open_audit_count` is recomputed on closure as well, and every advance increments the case's `version`. `CLOSED_REFUTED` and `CLOSED_SUSTAINED` are both terminal.

### 3.9. Recordkeeping Retention and Destruction

Federal regulation requires drawback records to be retained for three years after payment. The three `ComplianceRecord` documents auto-created at filing — `ENTRY_DOCS`, `EXPORT_PROOF`, and `MATCHING_WORKSHEET` — sit in `RETAINED` with a null `retention_until` while the claim remains unpaid, meaning they are retained indefinitely. Payment starts the clock: each record's `retention_until` becomes the claim's `paid_at` plus three years.

Destruction is a two-step, sweep-mediated process, never an immediate one. When the ops sweep of §2.8 finds a `RETAINED` record whose `retention_until` is set and has been reached by the logical clock — inclusively — it flips the record to `ELIGIBLE_FOR_DESTRUCTION` and increments its `version`. Only then may a `ComplianceManager` certify destruction, moving the record to its terminal `DESTROYED` state; attempting destruction from `RETAINED` is rejected with `ERR_RECORD_NOT_ELIGIBLE`, and attempting it against an already `DESTROYED` record is rejected with `ERR_ALREADY_TERMINAL`.

## 4. Endpoint Definitions

Operations that create new stand-alone resources return `201 Created`. Operations that modify an existing resource — state transitions, corrections, payments, cascades — return `200 OK`. All endpoints are mounted under the `/customs` prefix. Request payloads, derived fields, and side effects for every operation are specified in §3; this table is the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customs/clients` | Onboard a client | FirmAdmin |
| GET | `/customs/clients/{id}` | Get a client including computed aggregates | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| GET | `/customs/clients` | List clients, filterable by `engagement_status` | FirmAdmin, Analyst, LicensedBroker, ComplianceManager |
| PATCH | `/customs/clients/{id}` | Change a client's engagement status | FirmAdmin |
| POST | `/customs/classifications` | Create a classification in DRAFT | Analyst |
| GET | `/customs/classifications/{id}` | Get a classification | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| GET | `/customs/classifications` | List classifications, filterable by `client_id`, `supersedes_id`, `status` | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| POST | `/customs/classifications/{id}/submit` | Submit a classification for review | Analyst |
| POST | `/customs/classifications/{id}/review-decision` | Certify a classification or send it back for rework | LicensedBroker |
| POST | `/customs/classifications/{id}/supersede` | Create a successor classification; the old one becomes SUPERSEDED | Analyst |
| POST | `/customs/binding-rulings` | File a binding-ruling request | LicensedBroker |
| GET | `/customs/binding-rulings/{id}` | Get a binding ruling | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| GET | `/customs/binding-rulings` | List rulings, filterable by `classification_id`, `status` | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| POST | `/customs/binding-rulings/{id}/outcome` | Record the CBP ruling outcome; ISSUED re-rates the classification | LicensedBroker |
| POST | `/customs/import-entries` | Register an import entry | Analyst |
| GET | `/customs/import-entries/{id}` | Get an import entry | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| GET | `/customs/import-entries` | List entries, filterable by `client_id`, `classification_id`, `status` | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| POST | `/customs/import-entries/{id}/correct` | Correct entry figures under optimistic concurrency | Analyst |
| POST | `/customs/export-shipments` | Register an export shipment | Analyst |
| GET | `/customs/export-shipments/{id}` | Get an export shipment | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| GET | `/customs/export-shipments` | List shipments, filterable by `client_id`, `status` | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| POST | `/customs/claims` | Create a drawback claim in DRAFT | Analyst |
| GET | `/customs/claims/{id}` | Get a claim | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| GET | `/customs/claims` | List claims, filterable by `client_id`, `claim_type`, `status` | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| PUT | `/customs/claims/{id}` | Update a DRAFT claim's period or type under optimistic concurrency | Analyst |
| POST | `/customs/claims/{id}/lines` | Add a matched line to a DRAFT claim | Analyst |
| DELETE | `/customs/claims/{id}/lines/{lineId}` | Void an ACTIVE line on a DRAFT claim | Analyst |
| GET | `/customs/claim-lines/{id}` | Get a claim line | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| GET | `/customs/claim-lines` | List claim lines, filterable by `claim_id`, `import_entry_id`, `export_shipment_id`, `status` | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| POST | `/customs/claims/{id}/file` | File the claim; freezes the claimed amount and creates compliance records | LicensedBroker |
| POST | `/customs/claims/{id}/review` | Record the CBP review outcome | LicensedBroker |
| POST | `/customs/claims/{id}/deficiency-response` | Respond to a deficiency notice | Analyst, LicensedBroker, ClientContact |
| POST | `/customs/claims/{id}/record-payment` | Record recovered duty; creates the invoice and starts retention | FirmAdmin |
| POST | `/customs/claims/{id}/cancel` | Cancel a DRAFT claim and void its lines | Analyst |
| POST | `/customs/tariff-measures` | Publish a tariff measure or exclusion | FirmAdmin |
| GET | `/customs/tariff-measures/{id}` | Get a tariff measure | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| GET | `/customs/tariff-measures` | List measures, filterable by `hts_code_prefix`, `measure_type`, `status` | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| POST | `/customs/tariff-measures/{id}/revoke` | Revoke an ACTIVE measure and recompute matching entries | FirmAdmin |
| GET | `/customs/invoices/{id}` | Get an invoice | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| GET | `/customs/invoices` | List invoices, filterable by `client_id`, `claim_id`, `status` | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| POST | `/customs/invoices/{id}/payments` | Record a client payment against an invoice | FirmAdmin |
| POST | `/customs/invoices/{id}/void` | Void an unpaid invoice | ComplianceManager |
| POST | `/customs/audit-cases` | Open an audit case | FirmAdmin |
| GET | `/customs/audit-cases/{id}` | Get an audit case | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| GET | `/customs/audit-cases` | List audit cases, filterable by `client_id`, `claim_id`, `status` | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| POST | `/customs/audit-cases/{id}/advance` | Advance the audit workflow | ComplianceManager |
| GET | `/customs/records/{id}` | Get a compliance record | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| GET | `/customs/records` | List records, filterable by `claim_id`, `doc_type`, `status` | FirmAdmin, Analyst, LicensedBroker, ComplianceManager, ClientContact |
| POST | `/customs/records/{id}/destroy` | Certify destruction of an ELIGIBLE record | ComplianceManager |
| POST | `/customs/ops/run_sweep` | Expire due measures and flip due records to destruction-eligible | FirmAdmin |
| POST | `/customs/_clock/set_current_utc` | Set the server's logical clock | FirmAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CLIENT_NOT_ACTIVE` | 409 |
| `ERR_CLASSIFICATION_NOT_CERTIFIED` | 409 |
| `ERR_CROSS_CLIENT_REFERENCE` | 422 |
| `ERR_DUPLICATE_ENTRY_NUMBER` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_MEASURE_WINDOW_OVERLAP` | 409 |
| `ERR_MEASURE_BLOCKED_BY_CLAIM_LINES` | 409 |
| `ERR_CLAIM_PERIOD_OVERLAP` | 409 |
| `ERR_FILING_DEADLINE_PASSED` | 422 |
| `ERR_DEFICIENCY_LIMIT_REACHED` | 409 |
| `ERR_MATCH_QUANTITY_EXCEEDED` | 422 |
| `ERR_MATCH_INCOMPATIBLE` | 422 |
| `ERR_EXPORT_VALUE_POOL_EXCEEDED` | 422 |
| `ERR_APPROVED_EXCEEDS_CLAIMED` | 422 |
| `ERR_PAID_AMOUNT_MISMATCH` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 |
| `ERR_RECORD_NOT_ELIGIBLE` | 409 |
| `ERR_RESPONSE_PAST_DUE` | 422 |
| `ERR_ENTRY_LOCKED_BY_FILED_CLAIM` | 409 |
| `ERR_INTERNAL` | 500 |
