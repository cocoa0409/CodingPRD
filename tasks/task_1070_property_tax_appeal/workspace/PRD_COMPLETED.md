# Property-Tax Appeal API — Product Requirements Document

## 1. Introduction

Property owners routinely overpay when a county assessor's noticed value drifts above true market value, yet the process of challenging that value — assembling comparable sales, meeting a jurisdiction's filing window, appearing at a hearing, and negotiating a settlement — is specialized enough that most taxpayers never pursue it. This document specifies the backend service for a **contingency-fee property-tax appeal firm**: a practice that takes on that work at its own risk and is paid only a percentage of the tax savings it actually secures. The platform must therefore track the full lifecycle from parcel and assessment intake, through evidence-driven valuation and appeal filing, to hearing representation, settlement negotiation, and finally the billing of a tiered contingency fee against realized savings.

The system serves four distinct kinds of operator whose duties are deliberately kept apart. Firm administrators configure the jurisdictions, staff, clients, and fee agreements that everything else references. Analysts do the casework — analyzing parcels, curating comparable evidence, filing appeals, appearing at hearings, and proposing settlements — but the firm enforces a four-eyes discipline in which the analyst who authors a settlement offer may never be the one who accepts it. A separate billing function issues invoices and records payments, and is structurally barred from working appeals. Clients themselves reach the platform only through a read-mostly portal where they accept fee terms, submit exemption paperwork, respond to offers, and pay.

Because a single appeal outcome ripples across an assessment's finalized value, a client's running fee ledgers, and the firm's billable position, the service treats consistency as immediate and non-negotiable. Multi-year assessments, cascading state changes, compensating reversals for withdrawn or voided work, and a dual-variant valuation-and-pricing engine are all first-class concerns described in the sections that follow. A test-driving logical clock governs every deadline and expiry so that time-sensitive rules are exercised deterministically.

## 2. Global Specifications & System-Wide Principles

All resource collections are mounted under the `/api` prefix. Every endpoint consumes and produces `application/json`.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. If either header is absent, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are `FirmAdmin`, `Analyst`, `Billing`, and `Client`.

- A `FirmAdmin` is the firm's configuration operator: it creates analysts, clients, jurisdictions, and fee agreements, decides exemption claims, voids invoices, and drives the logical clock. When `X-User-Role` is `FirmAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.
- A `Billing` operator issues invoices and records payments but is barred from casework. When `X-User-Role` is `Billing`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared against any entity's `id`.
- An `Analyst` performs casework. When `X-User-Role` is `Analyst`, `X-User-ID` is the `id` of the acting `Analyst` entity. The server records it where a transition captures the actor — for example, as `created_by_analyst_id` and `accepted_by_analyst_id` on a settlement offer — and uses it for the segregation-of-duties comparison. This implementation does not otherwise enforce analyst ownership: an `Analyst`'s `X-User-ID` is never compared against a resource's analyst foreign key as an access gate — the segregation-of-duties comparison on settlement-offer acceptance is the only actor-identity check applied to analysts.
- A `Client` is a portal user. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client` entity; ownership checks on any resource that references a `Client` compare the resource's owning-client foreign key to `X-User-ID`. A client may read only its own parcels, assessments, appeals, offers, and invoices, and may fetch only its own client record.

When a `Client` on the portal targets a resource whose owning-client foreign key does not match `X-User-ID`, the request is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403); this ownership gate is applied only on the client's own read (`GET`) endpoints. For a resource addressed by `id` whose ownership resolves through a foreign-key chain, that resource's own existence is confirmed first, so a non-existent target yields `ERR_NOT_FOUND` (404) before the ownership check; the sole exception is fetching a client by `id`, where the Client self-ownership comparison (`id` vs `X-User-ID`) is applied before existence.

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

### 2.3. Pagination

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, must be at least 1, and may be no greater than 100; the `offset` defaults to 0 and must be at least 0. A request that violates these bounds is rejected as an invalid request.

Every list is sorted by `created_at` in ascending order (oldest first) before pagination is applied. The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the query before the page window is applied and `has_more` is true exactly when records remain beyond the returned page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource is assigned a server-minted `id` that is an opaque UUID string carrying no type prefix. Each resource also records a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, captured when the resource is first created.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `version` begins at 1 when the resource is created and increases by exactly 1 on every mutation that changes the resource; `updated_at` is refreshed to the current logical-clock instant on each such mutation. The one exception is the payment record: a `Payment` is an immutable audit fact that is written once and never altered, so it carries only `id` and `created_at` — it has neither an `updated_at` nor a `version`. Every other resource in this system carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Monetary and Ratio Precision

All money is stored and exchanged in integer cents; there are no fractional-cent amounts anywhere in the system. Wherever a computation produces a fractional number of cents — a tax figure, an adjusted comparable value, a contingency fee — the result is rounded half up to the nearest whole cent, meaning a value whose fractional part is exactly one half is rounded away from zero to the next cent. Ratio and rate inputs such as `equalization_ratio`, `millage_rate`, the contingency tier percentages, and a comparable's `adjustment_pct` are decimal numbers; they participate in intermediate arithmetic at full precision, and rounding is applied only where a rule below explicitly names a rounding step. When a rule pins the order of rounding relative to aggregation, that order is binding and is called out at the point of use.

### 2.6. The Logical Clock

The service keeps a test-driving logical clock rather than reading wall-clock time. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real time. A `FirmAdmin` may advance the clock by supplying a target instant in the `to_iso8601` field of the clock-setting capability. Every deadline, expiry, and window evaluation in this document — filing-window checks, settlement-offer expiry, and every `accepted_at`, `filed_date`, `issued_date`, `paid_date`, `received_date`, and `decision_date` stamp — reads this logical clock.

### 2.7. Optimistic Concurrency Control

Creating a settlement offer against an appeal is guarded by optimistic concurrency control. The create-settlement-offer request must carry an `expected_appeal_version` field holding the `version` of the parent `Appeal` that the client last observed. If `expected_appeal_version` does not equal the appeal's current `version`, the request is rejected with `ERR_STALE_APPEAL_VERSION` (HTTP 412). Because each successful offer creation itself increments the parent appeal's `version` by 1, an offer legitimately supersedes the negotiating position of the prior round; a second create that still carries the earlier, now-stale `expected_appeal_version` is refused, preventing a writer from overwriting a negotiation state it has not yet seen. No other endpoint in this system accepts or requires a version field.

### 2.8. Cascading Consistency and Compensating Reversals

Many operations mutate more than one resource at once, and the system applies every such cascade atomically and immediately. When an appeal is filed, its parent assessment is driven from `NOTICED` to `UNDER_APPEAL`; when the appeal reaches a terminal outcome the assessment moves on to `FINALIZED`; and when an appeal is withdrawn the assessment is compensated back to `NOTICED`. Every one of these dependent mutations bumps the affected resource's `version` and refreshes its `updated_at`, exactly as a direct edit would.

Two flows are explicitly designed as compensating pairs whose invariants must hold. Filing an appeal and then withdrawing it must leave the assessment's effective `assessed_value_cents` exactly as it was before filing — the withdrawal reversal restores `NOTICED` without altering the assessed base. Likewise, issuing an invoice and then voiding it must leave the client's `lifetime_fees_billed_cents` exactly as it was before issue. These conserved-quantity guarantees are described in the workflow sections that own them.

### 2.9. Nested Resource Retrieval and Referential Validation

Several endpoints address a resource through a parent path segment — evidence, settlement offers, and payments are reached beneath their owning appeal or invoice. Path and body references are validated left to right: each referenced resource must exist, and the first missing reference encountered yields `ERR_NOT_FOUND` (HTTP 404) before any deeper reference or business rule is considered. Only once every referenced resource is confirmed to exist does the system evaluate request-body completeness, and a request missing a required field or carrying a value of the wrong type or an unrecognized enum member is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

### 2.10. Order of Validation

When several checks could fail on one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a missing or unknown-role credential surfaces as `ERR_UNAUTHENTICATED` before anything else. Role authorization (`ERR_UNAUTHORIZED`) is next, followed by the ownership check for entity-backed roles (`ERR_FORBIDDEN_NOT_OWNER`) — which, for a target resource whose ownership resolves through a foreign-key chain, is applied only after that resource's own existence is confirmed, so a missing target surfaces `ERR_NOT_FOUND` (404) ahead of `ERR_FORBIDDEN_NOT_OWNER` (the client self-fetch by `id` is the one case where the ownership comparison precedes existence). Existence of all referenced resources (`ERR_NOT_FOUND`) is then confirmed, after which request-body shape and types are validated (`ERR_INVALID_REQUEST`). Only then are stateful and business rules considered: whether the target is in a state from which the transition is defined (`ERR_INVALID_STATE`), and then the domain-specific preconditions — cross-entity state gates, segregation of duties, referential-activation gates, temporal deadlines, and the various business-constraint and fiscal checks — as described alongside the workflows they guard. Uniqueness conflicts on creation surface as `ERR_DUPLICATE`. Where a single endpoint layers multiple domain checks, the precise relative order for that endpoint is stated in its workflow narrative.

## 3. Business Logic & Workflows

### 3.1. Firm Setup: Staff, Clients, Jurisdictions, and Fee Agreements

A `FirmAdmin` populates the reference data the rest of the platform depends on. Creating an analyst records a `full_name`, a login/contact `email` that must be unique across analysts (a reused email is rejected with `ERR_DUPLICATE`), and a state agent `license_number` that authorizes hearing representation; an `active` flag defaults to true when omitted and is recorded on the analyst, but this implementation does not gate appeal or hearing assignment on it — an inactive analyst may still be named as an appeal's `analyst_id` or a hearing's `representative_id`. Creating a client records the taxpayer's `full_name`, a unique portal `email` (a reused email is rejected with `ERR_DUPLICATE`), and an `entity_type` of either `INDIVIDUAL` or `BUSINESS`. A client's `portal_enabled` flag defaults to true and is recorded on the client, but this implementation does not gate portal authentication on it. Every client also carries two running ledger figures, `lifetime_fees_billed_cents` and `outstanding_balance_cents`, both of which begin at 0 at creation and are maintained by the billing flows described in §3.8.

A jurisdiction captures the rules of one taxing authority. Beyond its `name` and two-letter `state_code`, it declares a `filing_window_days` — the number of days after an assessment's notice date within which an appeal may still be filed, inclusive of the final day — which must be at least 1. Its `equalization_ratio`, the legal assessment-to-market ratio used by one of the valuation variants, must be greater than 0 and no greater than 1 (for example, 0.90). Violating either bound — a `filing_window_days` below 1 or an `equalization_ratio` outside `(0, 1]` — is rejected with `ERR_INVALID_REQUEST`. Three further settings tune scheduling and process: `informal_review_available`, defaulting to true, states whether the jurisdiction offers an informal-review step before a formal hearing; `hearing_room_capacity`, defaulting to 3, caps how many concurrently overlapping scheduled hearings one docket room may hold; and `rep_travel_buffer_minutes`, defaulting to 60, sets the minimum gap required between two scheduled hearings for the same representative in that jurisdiction.

Each taxpayer engages the firm under a contingency fee agreement. Creating one binds it to a client via the payload's `client_id` and records the marginal contingency structure: a first-band rate `contingency_tier1_pct` (defaulting to 0.40), a middle-band rate `contingency_tier2_pct` (defaulting to 0.33), and a top-band rate `contingency_tier3_pct` (defaulting to 0.25), together with the band boundaries `tier1_ceiling_cents` (defaulting to 50000) and `tier2_ceiling_cents` (defaulting to 150000), and a `minimum_fee_cents` floor (defaulting to 15000). A new agreement begins in `PENDING` `status`, and its `accepted_at` timestamp is null until it becomes active. An agreement becomes billable only when the bound client accepts it, moving it from `PENDING` to `ACTIVE`: acceptance is allowed only while the agreement is still `PENDING`, and only when the acting client's `X-User-ID` equals the agreement's `client_id`. On acceptance the `accepted_at` timestamp is stamped from the logical clock.

### 3.2. Parcels, Annual Assessments, and the Exemption Ledger

An analyst registers a parcel for a client in a jurisdiction, supplying the owning `client_id`, the taxing `jurisdiction_id`, an assessor parcel number `apn`, a street `address`, and a `property_class` of `RESIDENTIAL`, `COMMERCIAL`, `INDUSTRIAL`, or `LAND`. The gross `building_area_sqft` may be supplied and defaults to 0. A parcel's `apn` must be unique within its jurisdiction; a second parcel reusing an `apn` in the same jurisdiction is rejected with `ERR_DUPLICATE`.

Against a parcel an analyst records an annual assessment, identifying the `parcel_id` and the `tax_year` it values — the pairing of parcel and tax year must be unique, so the system supports a distinct assessment per year but rejects a duplicate year for the same parcel with `ERR_DUPLICATE`. The assessment carries the assessor's noticed total, `original_assessed_value_cents` (which must be zero or greater and is the immutable baseline against which savings are later measured), optional `land_value_cents` and `improvement_value_cents` components each defaulting to 0, a `millage_rate` in mills that must be greater than 0, and the `notice_date` on which the notice was issued. A constraint violation here — a negative `original_assessed_value_cents` or a non-positive `millage_rate` — is rejected with `ERR_INVALID_REQUEST`. A new assessment begins in `NOTICED` `status`. At creation its effective `assessed_value_cents` is set equal to `original_assessed_value_cents`, and its `projected_annual_tax_cents` is computed immediately; its `total_approved_exemption_cents` starts at 0.

The projected annual tax reconciles a derived taxable base against approved exemptions. The `total_approved_exemption_cents` of an assessment is the sum of the `exemption_value_cents` of every exemption claim for the same `parcel_id` and `tax_year` that currently sits in `APPROVED` status. The `projected_annual_tax_cents` is then the effective `assessed_value_cents` less that approved-exemption total, multiplied by the `millage_rate` and divided by 1000, with the result rounded half up to whole cents; if approved exemptions exceed the assessed value, the taxable base is floored at 0 before the rate is applied so the projected tax is never negative. This figure is recomputed whenever an exemption on the assessment is approved or denied and again when the assessment is finalized on a new assessed value.

An exemption claim is prepared against a parcel and tax year. Its payload names the `parcel_id`, the `tax_year` it applies to (matched against the parcel's assessment of that same year), an `exemption_type` — one of `HOMESTEAD`, `SENIOR`, `VETERAN`, `AGRICULTURAL`, or `DISABLED` — and the `exemption_value_cents` reduction it confers, which must be zero or greater (a negative value is rejected with `ERR_INVALID_REQUEST`). A claim opens in `DRAFT` `status`. Either an analyst or the client may submit it, moving it from `DRAFT` to `SUBMITTED`, which is permitted only while the claim is still `DRAFT`. A `FirmAdmin` then decides a submitted claim by supplying a `decision` of either APPROVE or DENY. Approval is allowed only while the claim is `SUBMITTED` and only when an assessment already exists for the claim's `parcel_id` and `tax_year` (an APPROVE decision when no such assessment exists is rejected with `ERR_INVALID_STATE`); it moves the claim to `APPROVED`. Approval cascades: the matching assessment's `total_approved_exemption_cents` increases by the claim's `exemption_value_cents`, its `projected_annual_tax_cents` is recomputed, and its `version` is incremented; and for any non-terminal appeal on that assessment, the appeal's `projected_client_tax_bill_cents` is recomputed and the appeal's `version` is incremented. Denial, also permitted only from `SUBMITTED`, moves the claim to `DENIED` and carries no cascade — the approved-exemption total is unchanged, so a recomputation would return the same values. A decide request on a claim that is not `SUBMITTED` is rejected as an invalid state transition.

### 3.3. Comparable Evidence and the Opinion of Value

Valuation rests on comparable properties. An analyst attaches an evidence row to an appeal, providing the comparable's `comp_address`, its `sale_price_cents` (zero or greater), its `sale_date`, and the comparable's own `comp_assessed_value_cents` (zero or greater); a negative `sale_price_cents` or `comp_assessed_value_cents` is rejected with `ERR_INVALID_REQUEST`. A net condition-or-quality `adjustment_pct` may be supplied — for instance, a value of -0.05 to mark the comparable down by five percent — and defaults to 0.0. Whether the comparable participates in the valuation set is governed by the `included` flag, which defaults to true. At the moment an evidence row is created the system computes its `adjusted_sale_value_cents` as the `sale_price_cents` multiplied by the quantity one plus the `adjustment_pct`, rounded half up to whole cents. This per-comparable rounding is pinned to happen before any aggregation across comparables.

Two opinion-of-value methods turn the included evidence into a single requested value, and which one runs is fixed on the appeal itself (see §3.4). Both operate over the set of that appeal's evidence rows whose `included` is true, ordered by creation time, and both take the **median** of a list of per-comparable figures. To take the median, the figures are sorted in ascending order; if the count is odd the middle figure is the median, and if the count is even the median is the mean of the two middle figures, rounded half up to whole cents. Under the sales-comparison method the list is each included comparable's `adjusted_sale_value_cents`. Under the assessment-equity method the list is instead, for each included comparable, that comparable's `comp_assessed_value_cents` divided by the jurisdiction's `equalization_ratio` and rounded half up to whole cents — the same comparable set measured differently, so the two methods generally yield different opinions. In both methods the per-comparable figure is rounded before the median is taken, and this nested rounding order is binding. If no included evidence exists at the moment valuation is demanded, the operation is rejected with `ERR_NO_EVIDENCE`.

### 3.4. Filing the Appeal

An analyst opens an appeal in `DRAFT` `status` against a single assessment, naming the `assessment_id` under challenge, the owning `analyst_id`, the `fee_agreement_id` whose tiers will later price the savings, and a `valuation_method` of either `SALES_COMPARISON` or `ASSESSMENT_EQUITY` that selects which opinion-of-value method computes the requested value at filing. Only one non-terminal appeal may exist per assessment; attempting a second while an appeal on that assessment is still live is rejected with `ERR_DUPLICATE`.

Filing advances the appeal from `DRAFT` to `FILED`, and its preconditions are evaluated in a fixed order. The appeal must first actually be in `DRAFT`; a file request against any other state is rejected as an invalid state transition. Next, the parent assessment must be in `NOTICED` — if it is already `UNDER_APPEAL` or `FINALIZED` the filing is rejected with `ERR_ASSESSMENT_NOT_APPEALABLE`. The filing must then fall within the jurisdiction's window: filing is allowed only while the current logical-clock date is on or before the assessment's `notice_date` advanced by the jurisdiction's `filing_window_days`, with the final day included; a date past that boundary is rejected with `ERR_FILING_DEADLINE_PASSED`. Finally, at least one included evidence row must exist for the appeal, or the filing is rejected with `ERR_NO_EVIDENCE`.

When those checks pass, filing performs a sequence of computations and one cascade. The appeal's `requested_value_cents` is set to the opinion of value produced by the selected method over the included evidence. From that requested value the system derives a provisional savings estimate, `projected_savings_cents`, and a provisional fee estimate, `projected_fee_cents`; the fee estimate is 0 whenever the projected savings are not positive. The appeal's `projected_client_tax_bill_cents` is also computed, and its `filed_date` is stamped from the logical clock. Filing then cascades to the parent assessment, advancing it from `NOTICED` to `UNDER_APPEAL` and incrementing its `version`. The provisional figures are shown to the client in the portal as estimates only and are never billed.

**Tax savings.** The savings figure is the assessment's immutable `original_assessed_value_cents` less the result value under consideration, multiplied by the assessment's `millage_rate`, divided by 1000, and rounded half up to whole cents. This calculation runs in two variants that differ only in the result value used. The **provisional** variant, computed at filing, uses the appeal's `requested_value_cents` and is stored in `projected_savings_cents`. The **final** variant, computed when the appeal is decided or settled, uses the realized outcome value — the `decision_value_cents` for a hearing decision or the `settlement_value_cents` for a settlement — and is stored in `realized_savings_cents`, and it is this final figure that drives billing.

**Projected client tax bill.** Separately, `projected_client_tax_bill_cents` is the appeal's `requested_value_cents` less the parent assessment's `total_approved_exemption_cents`, multiplied by the assessment's `millage_rate`, divided by 1000, and rounded half up to whole cents. It is recomputed whenever an exemption linked to that assessment is approved (and re-derived, unchanged, on denial), keeping the portal estimate reconciled with the current exemption position.

**Contingency fee.** The contingency fee is a marginal, tiered function of a savings amount, using the appeal's fee agreement. The savings amount is split across three bands. The portion up to `tier1_ceiling_cents` is charged at `contingency_tier1_pct`. The portion above `tier1_ceiling_cents` but not beyond `tier2_ceiling_cents` — that is, the savings above the first ceiling, but never more than the width between the first and second ceilings, and never less than zero — is charged at `contingency_tier2_pct`. The portion above `tier2_ceiling_cents`, if any, is charged at `contingency_tier3_pct`. These three band charges are summed in exact arithmetic, and the total is rounded half up to whole cents exactly once, after the three bands are added rather than band by band. Whenever the savings amount is greater than zero, the fee is then raised to at least `minimum_fee_cents`: the final fee is the larger of that floor and the rounded tier total. When the savings amount is not positive, no fee is charged and the floor does not apply. Like tax savings, the fee runs in a **provisional** variant at filing — over `projected_savings_cents`, stored in `projected_fee_cents` and never billed — and a **final** variant when the terminating invoice is created, over `realized_savings_cents`, which becomes the billed `fee_amount_cents`.

### 3.5. Hearings and Scheduling Constraints

Once an appeal is filed it may proceed either directly to a hearing or first through informal review. Where the jurisdiction offers it, an analyst may escalate a filed appeal to informal review, moving the appeal from `FILED` to `INFORMAL_REVIEW`; this is permitted only when the appeal is `FILED` and only when the jurisdiction's `informal_review_available` is true; a request against a jurisdiction that does not offer informal review is rejected with `ERR_INVALID_STATE`.

Scheduling a hearing creates a hearing record and advances the appeal into `HEARING_SCHEDULED` from either `FILED` or `INFORMAL_REVIEW`. The scheduling payload names the appearing `representative_id` — a licensed analyst — the `docket_room` within the appeal's jurisdiction, and the `scheduled_start` and `scheduled_end` bounding the appearance. The hearing occupies the half-open interval running from `scheduled_start` up to but not including `scheduled_end`, and `scheduled_end` must be strictly later than `scheduled_start`; a non-positive interval is rejected with `ERR_INVALID_VALUE`. A new hearing opens in `SCHEDULED` `status`.

Two overlap constraints guard scheduling, and they are checked in order after the appeal's state is confirmed. First, the representative must have travel room: if the proposed interval falls closer than the jurisdiction's `rep_travel_buffer_minutes` to any other `SCHEDULED` hearing of the same representative in that jurisdiction, the request is rejected with `ERR_REPRESENTATIVE_UNAVAILABLE`; a gap exactly equal to the buffer is allowed. Second, the docket room must have space: if the number of already-`SCHEDULED` hearings overlapping the proposed interval in the same jurisdiction-and-`docket_room` combination is already at or above the jurisdiction's `hearing_room_capacity`, the request is rejected with `ERR_DOCKET_ROOM_FULL`. Only after both overlap checks pass, and after the interval's own validity is confirmed, is the hearing recorded.

A scheduled hearing is later resolved. Holding it moves it from `SCHEDULED` to `HELD` and records the free-text `outcome_note` supplied with the request. Cancelling it moves it from `SCHEDULED` to `CANCELLED`, which frees that representative and docket-room slot so it no longer counts against the buffer and capacity checks for future scheduling. Either action is permitted only while the hearing is still `SCHEDULED`.

### 3.6. Settlement Negotiation

At any live stage of an appeal the firm and the jurisdiction may negotiate a settlement through a cyclic exchange of offers. Creating a settlement offer against an appeal records the `proposed_by` party — either `FIRM` or `JURISDICTION` — the proposed assessed `offer_value_cents` (which must be zero or greater; a negative value is rejected with `ERR_INVALID_VALUE`), and an `expires_at` instant after which the offer may no longer be accepted. A new offer opens in `PROPOSED` `status` with its `round_number` initialized to 1, and the system captures the creating analyst's `X-User-ID` into `created_by_analyst_id` for audit and for the four-eyes rule; its `accepted_by_analyst_id` remains null until the offer is accepted. Offer creation is guarded by the optimistic-concurrency rule of §2.7: the request must carry `expected_appeal_version` matching the parent appeal's current `version`, a mismatch is rejected with `ERR_STALE_APPEAL_VERSION`, and a successful create increments the parent appeal's `version` by 1. Creating an offer is not otherwise gated on the parent appeal's state: beyond the OCC guard and the `offer_value_cents` bound, no live-state precondition is checked at create time — the live-appeal requirement (`FILED`, `INFORMAL_REVIEW`, or `HEARING_SCHEDULED`) applies only to countering and accepting.

The negotiation loops between two states. Either an analyst or the client may counter an offer. Countering a `PROPOSED` offer records the supplied `offer_value_cents` as the new offer value and flips the `proposed_by` party between `FIRM` and `JURISDICTION`, moving the offer from `PROPOSED` to `COUNTERED`; this is allowed only while the offer is `PROPOSED` and the parent appeal is in one of `FILED`, `INFORMAL_REVIEW`, or `HEARING_SCHEDULED`. Countering a `COUNTERED` offer re-proposes the next round, moving it back from `COUNTERED` to `PROPOSED` and incrementing its `round_number` by 1; this is allowed only while the offer is `COUNTERED`. A counter request always requires an `offer_value_cents` of zero or greater (a negative value is rejected with `ERR_INVALID_VALUE`), but when re-proposing a `COUNTERED` offer the supplied value is not applied — only the round number advances. The offer thus cycles between `PROPOSED` and `COUNTERED` until it is accepted or rejected. Either party may also reject an offer that is in `PROPOSED` or `COUNTERED`, moving it to the terminal `REJECTED` state with no further effect.

Accepting an offer is the pivotal move and is restricted to an analyst. Its preconditions are checked in order: the offer must be in `PROPOSED` (otherwise an invalid state transition); the accepting analyst's `X-User-ID` must differ from the offer's `created_by_analyst_id`, enforcing segregation of duties — an attempt by the offer's own creator is rejected with `ERR_SEGREGATION_OF_DUTIES`; and the current logical clock must not be past the offer's `expires_at`, or the acceptance is rejected with `ERR_OFFER_EXPIRED`. Acceptance also requires the parent appeal to be in one of `FILED`, `INFORMAL_REVIEW`, or `HEARING_SCHEDULED`. On acceptance the offer moves from `PROPOSED` to `ACCEPTED`, the accepting analyst's `X-User-ID` is written into `accepted_by_analyst_id`, and the appeal is driven to settlement as described in §3.7.

### 3.7. Resolving the Appeal: Decisions, Settlements, and Withdrawals

An appeal reaches one of three terminal outcomes — `DECIDED`, `SETTLED`, or `WITHDRAWN` — and each carries a distinct set of cascades.

**Recording a hearing decision.** After a hearing has been held, an analyst records the tribunal's decision, moving the appeal from `HEARING_SCHEDULED` to `DECIDED`. The preconditions are ordered: the appeal must be `HEARING_SCHEDULED`; at least one hearing on the appeal must be in `HELD` status, or the request is rejected with `ERR_NO_HELD_HEARING`; and the supplied `decision_value_cents` must lie between 0 and the assessment's `original_assessed_value_cents` inclusive, or it is rejected with `ERR_INVALID_VALUE`. On success the `decision_value_cents` is stored, the appeal's `outcome_source` is set to `HEARING_DECISION`, and its `decision_date` is stamped. The appeal's `realized_savings_cents` is computed as the final tax-savings variant over the `decision_value_cents`. Two cascades follow: the parent assessment advances from `UNDER_APPEAL` to `FINALIZED`, its effective `assessed_value_cents` is set to the `decision_value_cents`, its `projected_annual_tax_cents` is recomputed on that new value, and its `version` is incremented; and a draft invoice is created for the appeal. The invoice is always created on a decision — even when realized savings are zero or negative — so its `gross_savings_cents` copies `realized_savings_cents` and its `fee_amount_cents` is the final contingency fee over those savings (which is 0 when savings are not positive), leaving the zero-savings boundary to be caught at issue time.

**Settling.** When an analyst accepts a settlement offer (§3.6), the appeal is driven to `SETTLED` from whichever live state it occupied — `FILED`, `INFORMAL_REVIEW`, or `HEARING_SCHEDULED`. The appeal's `settlement_value_cents` is set to the accepted offer's `offer_value_cents`, its `outcome_source` is set to `SETTLEMENT`, and its `realized_savings_cents` is computed as the final tax-savings variant over that settlement value. Three cascades follow in concert: the accepted offer moves to `ACCEPTED`; the parent assessment advances from `UNDER_APPEAL` to `FINALIZED`, its effective `assessed_value_cents` is set to the `settlement_value_cents`, its `projected_annual_tax_cents` is recomputed, and its `version` is incremented; and a draft invoice is created for the appeal with `gross_savings_cents` copied from `realized_savings_cents` and `fee_amount_cents` set to the final contingency fee over those savings (0 when savings are not positive).

**Withdrawing.** An analyst may withdraw an appeal that is in any of `FILED`, `INFORMAL_REVIEW`, or `HEARING_SCHEDULED`, moving it to `WITHDRAWN`. Withdrawal is a compensating reversal: the parent assessment is returned from `UNDER_APPEAL` back to `NOTICED`, and — critically — its effective `assessed_value_cents` is left unchanged, still equal to `original_assessed_value_cents`, so that a file-then-withdraw sequence provably leaves the assessed base exactly as it began. Any invoice still in `DRAFT` for that appeal is moved to `VOID` as part of the withdrawal.

### 3.8. Billing: Invoices and Payments

Every terminated appeal produces a draft invoice (§3.7), tied to its appeal by `appeal_id`, whose `gross_savings_cents` and `fee_amount_cents` were fixed at creation and whose `amount_paid_cents` begins at 0. Its `issued_date` and `paid_date` are null until the corresponding events occur, and it opens in `DRAFT` `status`.

A `Billing` operator issues a draft invoice, moving it from `DRAFT` to `ISSUED`. Issuance is gated by ordered checks after the state check: the appeal's fee agreement must be `ACTIVE`, or the request is rejected with `ERR_FEE_AGREEMENT_NOT_ACTIVE`; and the invoice's `gross_savings_cents` must be greater than 0, or the request is rejected with `ERR_NO_BILLABLE_SAVINGS` — this is the boundary that stops a zero-savings draft from ever billing. On issuance the `issued_date` is stamped, and the owning client's ledgers move together: `lifetime_fees_billed_cents` increases by the invoice's `fee_amount_cents`, and `outstanding_balance_cents` also increases by that `fee_amount_cents`. Each such client-ledger update — on issue, on void, and on each recorded payment — is a mutation that bumps the client's `version` and refreshes its `updated_at`. The `lifetime_fees_billed_cents` figure is thus the running sum of `fee_amount_cents` over the client's issued, non-voided invoices.

Payments are recorded against an issued invoice. Each payment names its `invoice_id`, an `amount_cents` that must be greater than 0 (a non-positive `amount_cents` is rejected with `ERR_INVALID_VALUE`), and a `method` of `CHECK`, `CARD`, or `ACH`; its `received_date` is stamped from the logical clock. A payment record is an immutable fact and carries no version. Recording a payment recomputes the invoice's `amount_paid_cents` as the sum of the `amount_cents` of all payments applied to it, and decreases the client's `outstanding_balance_cents` by the payment's `amount_cents`. When the accumulated `amount_paid_cents` first reaches or exceeds the invoice's `fee_amount_cents`, the invoice moves from `ISSUED` to `PAID` and its `paid_date` is stamped.

Finally, a `FirmAdmin` may void an issued invoice, moving it from `ISSUED` to `VOID`. Voiding is a compensating reversal of the issue-time ledger effects: the client's `lifetime_fees_billed_cents` is reduced by the invoice's `fee_amount_cents`, and its `outstanding_balance_cents` is reduced by the still-unpaid remainder, namely `fee_amount_cents` less `amount_paid_cents`. Because the lifetime figure is credited by the full fee on issue and debited by the full fee on void, an issue-then-void sequence provably leaves `lifetime_fees_billed_cents` exactly as it began.

## 4. Endpoint Definitions

Resource-creating endpoints return HTTP 201 with the created resource in `data`; state transitions and other modifications return HTTP 200 with the updated resource. Read endpoints return 200. The table below is a routing summary only; the request payloads, response side effects, and business rules for each endpoint are specified in the narratives of §2 and §3. List endpoints accept the `limit` and `offset` pagination parameters described in §2.3 in addition to any filters noted in their descriptions.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving; default `2026-07-01T00:00:00Z`). | FirmAdmin |
| POST | `/api/analysts` | Create an analyst (firm staff / licensed representative). | FirmAdmin |
| GET | `/api/analysts/{id}` | Fetch an analyst. | FirmAdmin, Analyst, Billing |
| POST | `/api/clients` | Create a client (taxpayer). | FirmAdmin |
| GET | `/api/clients/{id}` | Fetch a client; a Client may fetch only itself. | FirmAdmin, Billing, Client |
| POST | `/api/jurisdictions` | Create a taxing jurisdiction with deadline/room/buffer config. | FirmAdmin |
| GET | `/api/jurisdictions/{id}` | Fetch a jurisdiction. | FirmAdmin, Analyst |
| POST | `/api/fee-agreements` | Create a contingency fee agreement (PENDING) for a client. | FirmAdmin |
| GET | `/api/fee-agreements/{id}` | Fetch a fee agreement. | FirmAdmin, Billing, Client |
| GET | `/api/fee-agreements` | List fee agreements; filter by `client_id`. | FirmAdmin, Billing, Client |
| POST | `/api/fee-agreements/{id}/accept` | Client accepts the agreement (PENDING → ACTIVE). | Client |
| POST | `/api/parcels` | Register a parcel for a client in a jurisdiction. | Analyst |
| GET | `/api/parcels/{id}` | Fetch a parcel. | FirmAdmin, Analyst, Client |
| GET | `/api/parcels` | List parcels; filter by `client_id` and/or `jurisdiction_id`. | FirmAdmin, Analyst, Client |
| POST | `/api/assessments` | Create an annual assessment (NOTICED) for a parcel. | Analyst |
| GET | `/api/assessments/{id}` | Fetch an assessment. | FirmAdmin, Analyst, Client |
| GET | `/api/assessments` | List assessments; filter by `parcel_id`. | FirmAdmin, Analyst, Client |
| POST | `/api/exemption-claims` | Create an exemption claim (DRAFT) for a parcel and tax year. | Analyst, Client |
| GET | `/api/exemption-claims/{id}` | Fetch an exemption claim. | FirmAdmin, Analyst, Client |
| GET | `/api/exemption-claims` | List exemption claims; filter by `parcel_id`. | FirmAdmin, Analyst, Client |
| POST | `/api/exemption-claims/{id}/submit` | Submit a draft exemption claim (DRAFT → SUBMITTED). | Analyst, Client |
| POST | `/api/exemption-claims/{id}/decide` | Approve or deny a submitted exemption (SUBMITTED → APPROVED/DENIED). | FirmAdmin |
| POST | `/api/appeals` | Create an appeal (DRAFT) for an assessment. | Analyst |
| GET | `/api/appeals/{id}` | Fetch an appeal. | FirmAdmin, Analyst, Billing, Client |
| GET | `/api/appeals` | List appeals; filter by `assessment_id` / `analyst_id` / `fee_agreement_id`. | FirmAdmin, Analyst, Client |
| POST | `/api/appeals/{id}/evidence` | Attach a comparable-property evidence row. | Analyst |
| GET | `/api/appeals/{id}/evidence` | List evidence for an appeal. | FirmAdmin, Analyst |
| POST | `/api/appeals/{id}/file` | File the appeal (DRAFT → FILED); computes valuation and cascades the assessment. | Analyst |
| POST | `/api/appeals/{id}/request-informal-review` | Escalate a filed appeal to informal review (FILED → INFORMAL_REVIEW). | Analyst |
| POST | `/api/appeals/{id}/hearings` | Schedule a hearing; moves the appeal to HEARING_SCHEDULED. | Analyst |
| POST | `/api/appeals/{id}/record-decision` | Record the hearing decision (HEARING_SCHEDULED → DECIDED). | Analyst |
| POST | `/api/appeals/{id}/withdraw` | Withdraw an appeal (→ WITHDRAWN) with compensating reversal. | Analyst |
| POST | `/api/appeals/{id}/settlement-offers` | Create a settlement offer (PROPOSED); OCC-guarded on the parent appeal. | Analyst |
| GET | `/api/appeals/{id}/settlement-offers` | List settlement offers for an appeal. | FirmAdmin, Analyst, Client |
| GET | `/api/settlement-offers/{id}` | Fetch a settlement offer. | FirmAdmin, Analyst, Client |
| POST | `/api/settlement-offers/{id}/counter` | Counter/re-propose the offer (cyclic PROPOSED ↔ COUNTERED). | Analyst, Client |
| POST | `/api/settlement-offers/{id}/accept` | Accept the offer (PROPOSED → ACCEPTED); drives the appeal to SETTLED. | Analyst |
| POST | `/api/settlement-offers/{id}/reject` | Reject the offer (PROPOSED/COUNTERED → REJECTED). | Analyst, Client |
| GET | `/api/hearings/{id}` | Fetch a hearing. | FirmAdmin, Analyst |
| GET | `/api/hearings` | List hearings; filter by `appeal_id` and/or `representative_id`. | FirmAdmin, Analyst |
| POST | `/api/hearings/{id}/hold` | Mark the hearing HELD (SCHEDULED → HELD). | Analyst |
| POST | `/api/hearings/{id}/cancel` | Cancel the hearing (SCHEDULED → CANCELLED). | Analyst |
| GET | `/api/invoices/{id}` | Fetch an invoice. | FirmAdmin, Billing, Client |
| GET | `/api/invoices` | List invoices; filter by `appeal_id`. | FirmAdmin, Billing, Client |
| POST | `/api/invoices/{id}/issue` | Issue a draft invoice (DRAFT → ISSUED); debits client ledgers. | Billing |
| POST | `/api/invoices/{id}/void` | Void an issued invoice (ISSUED → VOID) with compensating reversal. | FirmAdmin |
| POST | `/api/invoices/{id}/payments` | Record a payment against an issued invoice; auto-transitions to PAID when covered. | Billing, Client |
| GET | `/api/invoices/{id}/payments` | List payments for an invoice. | FirmAdmin, Billing, Client |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the §2 and §3 narratives that govern the operation; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ASSESSMENT_NOT_APPEALABLE` | 409 |
| `ERR_NO_HELD_HEARING` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_FEE_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_FILING_DEADLINE_PASSED` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_NO_EVIDENCE` | 422 |
| `ERR_REPRESENTATIVE_UNAVAILABLE` | 409 |
| `ERR_DOCKET_ROOM_FULL` | 409 |
| `ERR_INVALID_VALUE` | 422 |
| `ERR_NO_BILLABLE_SAVINGS` | 409 |
| `ERR_STALE_APPEAL_VERSION` | 412 |
| `ERR_DUPLICATE` | 409 |
