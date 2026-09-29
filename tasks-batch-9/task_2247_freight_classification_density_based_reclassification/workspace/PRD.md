# LTL Freight Classification API — Product Requirements Document

## 1. Introduction

Less-than-truckload carriers price freight from a classification code, and that code is only as honest as the bill of lading it was copied from. A shipper declares a commodity, a weight, a piece count and three dimensions; the carrier bills on that declaration, then measures the freight at the origin terminal with a dimensioner and a scale and frequently discovers something else. The gap between declaration and measurement is the single largest source of revenue leakage and of customer friction in the LTL business, and resolving it fairly requires an auditable chain: a measurement, a classification decision traceable to a published standard, a correction notice backed by evidence, a bounded window in which the shipper may contest it, and a credit when the shipper is right.

This document specifies the LTL Freight Classification API, mounted under `/ltl`, which operationalizes that chain end to end. The system maintains published classification standards with their density bracket tables and commodity catalogues; it models and migrates customers between class-based, density-based and freight-all-kinds pricing programs; it captures dock measurements and fires automated reweigh and reclassification events; it issues correction notices with quantified evidence bundles and tier-adjusted dispute windows; it runs a segregated review process that can uphold, partially overturn or fully overturn a notice, allocating credits through a fixed waterfall; and it tracks each shipper's classification-accuracy record so that repeat offenders face shorter dispute windows and mandatory education.

Two design commitments run through every requirement below. First, money is conserved: a shipment's assessed total is always reconstructible from its original charge plus the frozen amounts of its notices minus the freight and fee buckets of its credit memos, so that a full overturn returns the shipment to exactly what it was billed at tender. Second, nobody audits their own work: the auditor who accepts an inspector's finding may not be that inspector, and the reviewer who resolves a dispute may not be the auditor who issued the notice under dispute.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply across every endpoint, and the cross-cutting domain principles that individual workflows in §3 depend upon.

### 2.1. Authentication, Roles and Acting Identity

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts. Six roles exist, and their names are spelled exactly as follows: `PricingAnalyst`, `TerminalOperator`, `FreightInspector`, `ClassificationAuditor`, `DisputeReviewer` and `Shipper`. A request missing either header, or naming a role outside those six, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is well-formed but is not among the roles authorized for the target operation is rejected with `ERR_ROLE_NOT_PERMITTED`.

Two of the six roles are entity-backed, meaning the header value doubles as a resource identifier:

- When `X-User-Role` is `TerminalOperator`, `X-User-ID` is the `id` of the acting `Terminal`; ownership checks on any resource that references a `Terminal` compare the resource's foreign-key field to `X-User-ID`. Concretely, a dock capture is only permitted when the addressed shipment's `origin_terminal_id` equals `X-User-ID`, and the capture records `terminal_id` and `captured_by_user_id` from that same header value.
- When `X-User-Role` is `Shipper`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. A `Shipper` may only tender or extend a bill of lading whose `customer_id` equals `X-User-ID`, may only dispute a correction notice whose shipment belongs to that customer, and may only supplement a dispute whose `filed_by_customer_id` equals `X-User-ID`.

The remaining four roles are opaque. When `X-User-Role` is `PricingAnalyst`, `FreightInspector`, `ClassificationAuditor` or `DisputeReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands attribution — as `inspector_user_id` on an inspection finding, as `accepted_by_user_id` when that finding is accepted, as `issued_by_user_id` on an issued correction notice, as `approved_by_user_id` on an approved exception agreement, and as `reviewer_user_id` on a dispute — but it never compares it to any entity's `id`.

Violating an entity-backed ownership rule yields `ERR_NOT_RESOURCE_OWNER`. Ownership is enforced on bill-of-lading tender, line addition, dock capture, dispute filing, dispute supplementation, and on read access to shipper-owned resources.

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

---

### 2.3. Pagination and List Filtering

Collection reads are paginated through two query parameters. `limit` caps the number of rows returned; it defaults to 10, may not be below 1, and may not exceed 100. `offset` is the number of rows to skip and defaults to 0. A `limit` outside the permitted range is a request-shape failure and is rejected with `ERR_INVALID_REQUEST`. Every list endpoint returns rows sorted by `created_at` in ascending order.

List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope.

Beyond pagination, list endpoints accept optional filter parameters named exactly after the attribute they filter on. Classification standard releases may be filtered by `status` and by `superseded_by_tariff_version_id`. Commodity profiles may be filtered by `tariff_version_id` and `classification_basis`. Pricing programs may be filtered by `customer_id`, `status`, `program_type` and `pinned_tariff_version_id`. Exception agreements may be filtered by `customer_id`, `commodity_profile_id` and `status`. Shipments may be filtered by `customer_id`, `origin_terminal_id`, `rate_program_id`, `tariff_version_id`, `class_status` and `billing_status`. Bill-of-lading lines may be filtered by `shipment_id` and `commodity_profile_id`. Capture events may be filtered by `shipment_id` and `terminal_id`. Inspection findings may be filtered by `shipment_line_id`, `found_commodity_profile_id` and `status`. Correction notices may be filtered by `shipment_id`, `status`, `basis_capture_event_id` and `supersedes_notice_id`. Disputes may be filtered by `correction_notice_id`, `filed_by_customer_id` and `status`. Credit memos may be filtered by `correction_notice_id` and `customer_id`. Repricing runs may be filtered by `new_tariff_version_id` and `status`.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every resource in the system is addressed by an `id`, which is a server-minted UUID carrying no type prefix. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first written.

Most resources — terminals, shipper accounts, classification standard releases, commodity profiles, pricing programs, exception agreements, shipments, bill-of-lading lines, inspection findings, correction notices, disputes and repricing runs — additionally carry `updated_at`, refreshed on every mutation of the resource, and `version`, an integer that increments by one on every mutation. Recomputation of a derived field counts as a mutation: when a dock capture rewrites a line's measured cube and class, or when a notice issuance recomputes a shipper's liability record, the affected rows have their `updated_at` refreshed and their `version` incremented.

Two resources are append-only records of something that already happened and therefore carry only `id` and `created_at`: a capture event and a credit memo. For those two, both `updated_at` and `version` are absent from the response entirely.

All time in this system comes from a server-held logical clock, never from wall-clock time. The clock's startup value is exactly `2026-08-01T00:00:00Z`, and until it is moved every timestamp the server stamps — `created_at`, `captured_at`, `published_at`, `issued_at`, `approved_at`, `accepted_at`, `billed_at`, `resolved_at`, `filed_at`, `modeled_at`, `committed_at`, `education_required_at`, `last_capture_at`, `effective_from`, `effective_to` where system-set, and every deadline and decay age — reads from that fixed default. An administrative test-driving capability, restricted to a `PricingAnalyst`, moves the clock to an instant supplied as `to_iso8601` and answers with the new value under the key `current_utc`. Every subsequent stamp and every window comparison uses the moved value.

### 2.5. Validation Ordering and Identifier Resolution

When several checks could reject the same request, the order in which they are evaluated is normative, because the client must be able to predict which `error_id` comes back. Checks are applied in the following sequence, and the first one that fails terminates the request:

1. Header presence and role validity — `ERR_UNAUTHENTICATED`.
2. Endpoint role authorization — `ERR_ROLE_NOT_PERMITTED`.
3. Resolution of every identifier templated into the URL, validated left to right, each against its own not-found code: `ERR_TERMINAL_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_TARIFF_VERSION_NOT_FOUND`, `ERR_COMMODITY_PROFILE_NOT_FOUND`, `ERR_RATE_PROGRAM_NOT_FOUND`, `ERR_EXCEPTION_AGREEMENT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_SHIPMENT_LINE_NOT_FOUND`, `ERR_CAPTURE_EVENT_NOT_FOUND`, `ERR_INSPECTION_FINDING_NOT_FOUND`, `ERR_CORRECTION_NOTICE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_CREDIT_MEMO_NOT_FOUND`, `ERR_REPRICING_RUN_NOT_FOUND`. The first identifier in the path that does not resolve determines the code returned.
4. Resolution of every foreign key supplied in the request body, validated in the order the fields are listed for that operation, against the same family of not-found codes.
5. Entity-backed ownership — `ERR_NOT_RESOURCE_OWNER`.
6. Request shape: required fields present, types correct, enum members recognized, numeric ranges honored (a contract discount is at least 0 and at most 0.75, piece counts are at least 1, weights are at least 1, `limit` is between 1 and 100 inclusive) — `ERR_INVALID_REQUEST`.
7. Domain-typed shape checks — `ERR_INVALID_CLASS_CODE` when a class-code field is not a recognized classification code, `ERR_INVALID_DIMENSIONS` when a dimension is zero, negative or carries more than one decimal place, `ERR_INVALID_DENSITY_BREAKS` when a bracket table is malformed, and `ERR_INVALID_INTERVAL` when an interval's end is not strictly after its start. These apply to drafting a classification standard, adding a commodity profile, drafting a pricing program, negotiating an exception agreement, adding a bill-of-lading line, recording an inspection finding, filing a dispute, resolving a dispute and opening a repricing run.
8. Stale-read protection on the three version-guarded writes described in §2.6 — `ERR_STALE_CUSTOMER_VERSION` or `ERR_STALE_SHIPMENT_VERSION`.
9. Whether the target row is currently in a state from which the requested trigger is declared at all — `ERR_INVALID_STATE_TRANSITION`, or one of the narrower state codes `ERR_NOTICE_NOT_DISPUTABLE`, `ERR_SHIPMENT_NOT_BILLED` and `ERR_SHIPMENT_ALREADY_BILLED`. This check applies to every action endpoint.
10. Cross-entity state preconditions — `ERR_DEVICE_OUT_OF_CALIBRATION`, `ERR_CUSTOMER_CLOSED`, `ERR_CUSTOMER_CREDIT_HOLD`, `ERR_TARIFF_NOT_PUBLISHED` and `ERR_EDUCATION_HOLD`. These guard dock capture, bill-of-lading tender, program approval, program activation, exception approval, notice issuance, repricing-run creation and dispute filing.
11. Segregation of duties — `ERR_SOD_VIOLATION`, guarding finding acceptance, supplement requests and dispute resolution.
12. Evidence sufficiency — `ERR_INSUFFICIENT_EVIDENCE`, guarding finding acceptance, notice issuance and dispute filing.
13. Temporal windows — `ERR_DISPUTE_WINDOW_CLOSED` on dispute filing and `ERR_TARIFF_EFFECTIVE_CONFLICT` on standard publication.
14. Uniqueness — a terminal's `code`, a shipper's `account_code` and a classification release's `code` are each globally unique, and a duplicate on any of those three is reported as `ERR_INVALID_REQUEST`; a shipment's `pro_number` is globally unique and a duplicate yields `ERR_DUPLICATE_PRO_NUMBER`; a line's `line_no` is unique within its own shipment and a duplicate yields `ERR_DUPLICATE_LINE_NO`.
15. Interval overlap — `ERR_EXCEPTION_OVERLAP` on exception agreements and `ERR_REPRICING_WINDOW_OVERLAP` on repricing runs.
16. Round and cardinality ceilings — `ERR_MAX_DISPUTE_ROUNDS` and `ERR_OPEN_NOTICE_EXISTS`, guarding dispute filing, dispute supplementation, supplement requests and manual notice creation.
17. Referential coherence — `ERR_LINE_NO_MISMATCH`, `ERR_TARIFF_MISMATCH`, `ERR_NO_RECLASS_BASIS` and `ERR_INVALID_PARTIAL_OUTCOME`, guarding dock capture, line addition, manual notice creation and dispute resolution.
18. Fiscal preconditions — `ERR_NO_ACTIVE_RATE_PROGRAM`, `ERR_NO_EFFECTIVE_TARIFF`, `ERR_ZERO_DELTA_NOTICE` and `ERR_NO_SHIPMENT_LINES`, guarding bill-of-lading tender, program approval, notice issuance and shipment billing.

The practical consequence of this ordering is that authorization always masks existence, existence always masks shape, shape always masks state, and state always masks fiscal viability. An auditor issuing a notice against a shipment that was never billed sees `ERR_SHIPMENT_NOT_BILLED` from step 9 rather than `ERR_ZERO_DELTA_NOTICE` from step 18, even when both conditions hold.

### 2.6. Stale-Read Protection on Account and Shipment Writes

Three write operations overwrite a decision that was itself derived from a parent resource's state, and each therefore requires the writer to prove which version of that parent it read. In all three cases the version field is a required input, not an optional one, and a mismatch against the parent's current `version` rejects the request without any side effect.

Activating an approved pricing program requires `expected_customer_version` carrying the client's last observed `version` of the target `Customer`. Activation legitimately supersedes whatever program was `ACTIVE` before, so a stale view of the customer is indistinguishable from an intentional supersede without the check. If the customer's `version` has advanced since the client read it, activation is rejected with `ERR_STALE_CUSTOMER_VERSION` at HTTP 412.

Changing a shipper's credit posture likewise requires `expected_customer_version` matching the customer's current `version`. Posture writes overwrite the previous posture decision outright, and that decision is normally made against the customer's strike count, liability indices and offender tier; requiring the version the writer read is the only defence against a posture set from out-of-date figures. A mismatch is rejected with `ERR_STALE_CUSTOMER_VERSION` at HTTP 412.

Drafting a correction notice manually requires `expected_shipment_version` matching the target `Shipment`'s current `version`. A manual notice is priced from the shipment's current measured state and may supersede an existing draft, so an auditor working from a read taken before a later dock capture rewrote the measured classification must re-read the shipment first. A mismatch is rejected with `ERR_STALE_SHIPMENT_VERSION` at HTTP 412.

No other endpoint accepts a version field, and no other endpoint performs a version check.

### 2.7. Rounding Discipline for Cube, Density, Money and Ratios

Every rounding in this system is round-half-up, and every rounding point is normative — the same inputs must produce the same digits regardless of implementation.

Cube is rounded twice, in a fixed order. The volume of a single handling unit is rounded to three decimal places first; only then is it multiplied by the piece count, and that product is rounded to two decimal places. Computing the whole line's volume in one multiplication and rounding once is a different answer, and because density sits directly on a bracket boundary in many real bills of lading, the difference can move a line into a different freight class. Densities in pounds per cubic foot are rounded to two decimal places. Weight variance percentages are rounded to two decimal places. Both liability indices are rounded to two decimal places, and the tier thresholds compare the already-rounded rolling index rather than an unrounded intermediate.

All money is stored and returned as an integer number of cents; there are no fractional cents anywhere in the system. Where a formula sums per-line raw amounts, §3 states explicitly whether the rounding happens once over the sum or once per line, because the two variants of a correction delta differ on exactly that point. Ratios expressed as fractions — the contract discount and the modelled revenue delta — carry four decimal places.

Class codes are never rounded or interpolated. Every class-code field must hold one of the eighteen recognized codes: 50, 55, 60, 65, 70, 77.5, 85, 92.5, 100, 110, 125, 150, 175, 200, 250, 300, 400 and 500. A value outside that set is rejected with `ERR_INVALID_CLASS_CODE`.

### 2.8. Segregation of Duties and Evidence Sufficiency

Two independence rules are enforced on `X-User-ID` and cannot be waived. A `ClassificationAuditor` may not accept an inspection finding whose `inspector_user_id` equals the auditor's own `X-User-ID`. A `DisputeReviewer` may not request a supplement on, nor resolve, a dispute whose correction notice carries an `issued_by_user_id` equal to the reviewer's own `X-User-ID`. Either violation is rejected with `ERR_SOD_VIOLATION` at HTTP 403.

Three evidence floors apply, all reported through `ERR_INSUFFICIENT_EVIDENCE` at HTTP 422. An inspection finding needs at least two photographs attached before it can be accepted. A correction notice needs an evidence bundle of at least one item before it can be issued. A dispute needs at least one attached document before it can be filed.

### 2.9. The Shipment Ledger Identity

A shipment's `assessed_total_cents` is a conserved quantity, not an accumulator that drifts. At every instant it equals the shipment's `original_charge_cents`, plus the sum over every correction notice of that shipment whose `status` is `ISSUED`, `DISPUTED`, `EVIDENCE_REQUESTED`, `UPHELD`, `PARTIALLY_OVERTURNED` or `OVERTURNED` of that notice's `applied_delta_cents` added to its `inspection_fee_cents`, minus the sum over the credit memos of those notices of each memo's `freight_credit_cents` added to its `fee_credit_cents`. Notices in `DRAFT` or `VOID` contribute nothing.

The third credit bucket, `interest_credit_cents`, is deliberately excluded from this identity. It is a goodwill payment made outside the freight ledger, which is why a full overturn returns `assessed_total_cents` to exactly `original_charge_cents` rather than below it.

A shipper's `offender_strike_count` is conserved in the same spirit: it always equals the number of correction notices against that shipper's shipments whose `status` is `ISSUED`, `DISPUTED`, `EVIDENCE_REQUESTED`, `UPHELD` or `PARTIALLY_OVERTURNED`.

### 2.10. Cascade Semantics Across the Terminal, Billing and Account Aggregates

A single operation in this system routinely writes three aggregates at once, and every one of those writes is part of the contract rather than an implementation detail. A dock capture writes the terminal's calibration counters, the addressed bill-of-lading lines, the shipment header and — when the variance gate or a class delta fires — a new correction notice. Issuing that notice writes the notice, both of the shipment's status dimensions, the shipment's money fields and the shipper account's strike count, both liability indices, offender tier, dispute window and education status. Resolving a dispute writes the dispute, the notice, possibly every line of the shipment, the shipment's billing dimension and money, a newly created credit memo, and the shipper account's strike and index record. §3 states each of these cascades in the workflow that owns it; none of them may be skipped, and each mutated row has its `updated_at` refreshed and its `version` incremented where those fields exist.

A shipment carries two status dimensions that advance on unrelated triggers and must not be conflated. `class_status` tracks the classification of the freight and takes the values `DECLARED`, `CAPTURED`, `UNDER_INSPECTION`, `RECLASS_PENDING`, `RECLASSED` and `CLASS_CONFIRMED`, starting at `DECLARED` and terminating at `CLASS_CONFIRMED`. `billing_status` tracks the money and takes the values `UNBILLED`, `BILLED`, `REBILLED`, `CREDITED` and `CLOSED`, starting at `UNBILLED` and terminating at `CLOSED`. Billing a shipment leaves `class_status` untouched; capturing a shipment leaves `billing_status` untouched. A shipper account is likewise two-dimensional: `billing_posture` takes `OPEN`, `CREDIT_HOLD` or `CLOSED` and starts at `OPEN`, while `education_status` takes `NONE`, `REQUIRED` or `COMPLETED` and starts at `NONE`; the two evolve entirely independently of one another.

Historical pinning is preserved across every supersession. When a newer classification standard supersedes an older one, shipments already pinned to the older release keep rating against it. When a newer pricing program retires an older one, shipments already pinned to the retired program keep rating against it.

## 3. Business Logic & Workflows

### 3.1. Publishing a Classification Standard and its Commodity Catalogue

Classification in this system always resolves against a versioned standard release. A `PricingAnalyst` drafts a release by supplying a `code` such as NMFC-2026A, an `effective_at` instant from which the release governs shipments picked up at or after it, and a `density_breaks` table. The release is created in `status` `DRAFT`, with `published_at` and `superseded_by_tariff_version_id` both null.

The `density_breaks` table is an ordered array whose elements each pair a `min_density_pcf` threshold with a `class_code`. Its order is normative: the array must be strictly descending by `min_density_pcf` and its final element must have a `min_density_pcf` of exactly 0, so that every possible density falls into some bracket. Bracket lookup scans the array in its declared order and returns the `class_code` of the first element whose `min_density_pcf` is less than or equal to the density being looked up. The lower bound is inclusive, which means a density landing exactly on a break belongs to the denser, lower-class bracket rather than to the one below it. Every `class_code` named in the table must be one of the eighteen recognized codes. A table that is empty, not strictly descending, does not terminate at 0, or names an unrecognized class is rejected with `ERR_INVALID_DENSITY_BREAKS`.

While a release is still `DRAFT`, the analyst populates its commodity catalogue. Each **commodity profile** is added with a payload naming the owning release as `tariff_version_id`, plus an `nmfc_item` classification item number, a `description` as printed on the bill of lading, and a `classification_basis` of either `DENSITY_BASED` or `FIXED_CLASS`. A `DENSITY_BASED` profile derives its class from measured or declared density; a `FIXED_CLASS` profile always rates at its `fixed_class_code`, which must be supplied for that basis and must be null for a density-based profile. Adding a commodity profile to a release that has left `DRAFT` is rejected with `ERR_INVALID_STATE_TRANSITION`.

Three characteristic codes accompany each profile, each defaulting to its most benign value: `handling_code` defaults to `STANDARD` and may also be `FRAGILE`, `HAZMAT` or `OVERLENGTH`; `stowability_code` defaults to `STACKABLE` and may also be `NON_STACKABLE` or `HAZ_SEGREGATED`; `liability_code` defaults to `LOW` and may also be `MEDIUM` or `HIGH`. Each code contributes a class floor, and the profile's computed `min_class_floor` is the largest of the three contributions. Handling contributes nothing for `STANDARD`, 100 for `FRAGILE`, 125 for `HAZMAT` and 110 for `OVERLENGTH`. Stowability contributes nothing for `STACKABLE`, 92.5 for `NON_STACKABLE` and 125 for `HAZ_SEGREGATED`. Liability contributes nothing for `LOW`, 70 for `MEDIUM` and 100 for `HIGH`. A profile whose three codes are all benign has a `min_class_floor` of 0, which means no floor at all. A hazmat, non-stackable, high-liability commodity has a floor of 125, since 125 exceeds both 125's stowability sibling value and 100.

Publishing a drafted release is the moment it starts governing new freight. Publication requires that at least one commodity profile already exists for the release and that its `effective_at` is strictly after the `effective_at` of the release that is currently the newest published one; a release whose effective instant does not clear that bar is rejected with `ERR_TARIFF_EFFECTIVE_CONFLICT`. On success the release moves `DRAFT → PUBLISHED` and `published_at` is stamped with the current logical instant. As a side effect the previously newest published release moves `PUBLISHED → SUPERSEDED` and has its `superseded_by_tariff_version_id` set to the newly published release's `id`. Shipments already pinned to the superseded release continue to rate against it unchanged. Publishing a release that is not `DRAFT` is rejected with `ERR_INVALID_STATE_TRANSITION`.

### 3.2. Shipper Accounts, Pricing Programs and Negotiated Exceptions

A shipper account is registered by a `PricingAnalyst` with an `account_code` and a legal `name`, and optionally an `education_strike_interval` that defaults to 3 and must be at least 1. On creation `billing_posture` is `OPEN`, `education_status` is `NONE`, `education_threshold_strikes` is initialised equal to `education_strike_interval`, `offender_strike_count` is 0, both `liability_index_rolling` and `liability_index_lifetime` are 0.00, `offender_tier` is `TIER_0`, `dispute_window_days` is 30, `education_required_at` is null and `active_program_type` is null.

Credit posture is moved by a `PricingAnalyst` supplying the target `billing_posture` together with `expected_customer_version`. The declared moves are `OPEN → CREDIT_HOLD`, `CREDIT_HOLD → OPEN`, `OPEN → CLOSED` and `CREDIT_HOLD → CLOSED`; any other combination is rejected with `ERR_INVALID_STATE_TRANSITION`, and `CLOSED` is terminal. A move to `CREDIT_HOLD` blocks new bill-of-lading tender while leaving everything else operable, and the return to `OPEN` re-enables it. A move to `CLOSED` blocks bill-of-lading tender, correction-notice issuance, pricing-program approval, pricing-program activation and exception-agreement approval. Every accepted posture move increments the account's `version` by one, which is precisely why the stale-read guard in §2.6 exists. Tendering while the account is `CREDIT_HOLD` is rejected with `ERR_CUSTOMER_CREDIT_HOLD`; any of the five guarded operations attempted while the account is `CLOSED` is rejected with `ERR_CUSTOMER_CLOSED`.

A **pricing program** is drafted for a shipper with a payload naming `customer_id`, the `program_type` — `CLASS_BASED`, `DENSITY_BASED` or `FAK` — a `base_rate_per_cwt_cents` of at least 1 cent per hundredweight, a `discount_pct` between 0 and 0.75 inclusive at four decimal places, a `min_charge_cents` of at least 0, and for a freight-all-kinds program a `fak_class_code` which must be supplied for `FAK` and must be null for the other two types. The program is created in `status` `MODELING` with `pinned_tariff_version_id`, `effective_from`, `effective_to` and `migration_recommendation` all null and with `baseline_revenue_cents`, `modeled_annual_revenue_cents`, `modeled_shipment_count` at 0 and `modeled_delta_pct` at 0.0000.

Approval is the modelling step. It requires that at least one published classification release exists — otherwise `ERR_NO_EFFECTIVE_TARIFF` — and that the shipper is not `CLOSED`. On success the program moves `MODELING → APPROVED`, `pinned_tariff_version_id` is pinned to the newest published release, and the customer impact model described in §3.3 populates `baseline_revenue_cents`, `modeled_annual_revenue_cents`, `modeled_delta_pct`, `modeled_shipment_count` and `migration_recommendation`.

Activation is guarded by `expected_customer_version` as described in §2.6 and additionally requires that the shipper is not `CLOSED`. On success the program moves `APPROVED → ACTIVE` and `effective_from` is stamped. As a side effect, whichever program of that shipper was previously `ACTIVE` moves `ACTIVE → RETIRED` with its `effective_to` stamped — shipments already pinned to it keep rating against it — the shipper's `active_program_type` is set to the newly activated program's `program_type`, and the shipper's `version` is incremented by one. Activating a program that is not `APPROVED` is rejected with `ERR_INVALID_STATE_TRANSITION`.

Negotiated **exception agreements** carve a single commodity out of the general tariff for a single shipper. An agreement is drafted with `customer_id`, `commodity_profile_id`, an `agreement_type` of either `EXCEPTION_CLASS` — which narrows one commodity — or `FAK` — which collapses that commodity into a freight-all-kinds class — an `agreed_class_code`, and a half-open coverage interval given as `effective_from` inclusive and `effective_to` exclusive, where `effective_to` must be strictly after `effective_from` or the request is rejected with `ERR_INVALID_INTERVAL`. The agreement is created in `status` `PENDING` with `approved_by_user_id` and `approved_at` null.

A pending agreement already reserves its interval: no two agreements in `PENDING` or `ACTIVE` may overlap on the same shipper-and-commodity pair, evaluated with half-open semantics so that one agreement ending exactly where the next begins is permitted. An overlap is rejected with `ERR_EXCEPTION_OVERLAP`. Only an `ACTIVE` agreement actually affects classification. Approval by a `PricingAnalyst` moves the agreement `PENDING → ACTIVE`, stamps `approved_by_user_id` from the acting `X-User-ID` and `approved_at` from the logical clock, and requires both that the shipper is not `CLOSED` and that no other `ACTIVE` agreement overlaps the same shipper-and-commodity interval.

### 3.3. Modelling a Migration and Repricing the Contract Book

The customer impact model answers one question: what would this shipper's historical freight have cost under this candidate program? Its shipment set is every shipment of the program's shipper whose `billing_status` is `BILLED`, `REBILLED`, `CREDITED` or `CLOSED`, iterated in ascending `created_at`; shipments still `UNBILLED` are excluded from both the baseline and the model. The cardinality of that set is `modeled_shipment_count`, and `baseline_revenue_cents` is the sum of each member's `assessed_total_cents`.

When the shipment set is empty, `modeled_annual_revenue_cents` is 0 and `modeled_delta_pct` is exactly 0.0000 as a literal, with no division performed.

Otherwise the model runs two passes, and the separation between them is normative. The first pass establishes the volume tier from undiscounted gross revenue. For each shipment in the set, the gross amount is the sum over its lines of the line's rating weight divided by 100, multiplied by the program's `base_rate_per_cwt_cents`, multiplied by the modelled class divided by 100, multiplied by that shipment's weight-break factor; the contract discount is treated as zero in this pass and the minimum charge is not applied, and the per-shipment sum is rounded to a whole number of cents. Adding those gross amounts across the shipment set gives the annual gross, and the volume tier is the factor of the first volume-discount element whose annual-gross threshold is less than or equal to that annual gross. The four elements are declared in descending threshold order: a 12 percent tier from $50,000 of annual gross, an 8 percent tier from $20,000, a 4 percent tier from $5,000, and a 0 percent tier from nothing at all.

The second pass applies the contract discount and then the volume tier. For each shipment, the raw summed per-line amount under modelled classification — computed with the program's own `discount_pct` applied, before any rounding and before any minimum-charge floor — is multiplied by one minus the volume tier factor, rounded to a whole number of cents, and then floored at the program's `min_charge_cents`. Summing across the shipment set yields `modeled_annual_revenue_cents`. The volume tier is derived once, from the first pass's undiscounted gross; it is never re-derived from the discounted second-pass revenue, and the model never iterates toward a fixed point.

`modeled_delta_pct` is the modelled annual revenue minus the baseline revenue, divided by the baseline revenue, rounded to four decimal places. The `migration_recommendation` follows directly: `MIGRATE_DENSITY_BASED` when the delta is at least 0.05, `HOLD_CLASS_BASED` when the delta is at most -0.05, and `NEGOTIATE_FAK` for anything strictly between those two bounds. The recommendation stays null while a program is still `MODELING` and has never been approved.

The modelled class of a line depends on the candidate program's own `program_type`. A `FAK` program models every line at the program's `fak_class_code`. A `DENSITY_BASED` program models every line at the bracket lookup, against the program's `pinned_tariff_version_id`, of the line's `measured_density_pcf` where one exists and of its `declared_density_pcf` otherwise. A `CLASS_BASED` program models every line at the line's own `effective_class_code`.

**Repricing runs** apply the same machinery to the whole contract book when a new classification standard is adopted. A run is opened by a `PricingAnalyst` naming the `new_tariff_version_id` under evaluation, a `scope` of `ALL_CLASS_BASED`, `ALL_DENSITY_BASED` or `ALL_ACTIVE`, and a shipment sample window given as `sample_window_start_at` inclusive and `sample_window_end_at` exclusive, the latter strictly after the former. The window is matched against each shipment's `pickup_at`. Runs are created in `status` `DRAFT` with `impacted_customer_count` and `aggregate_delta_cents` at 0 and `modeled_at` and `committed_at` null. No two runs in `DRAFT` or `MODELED` against the same standard may have sample windows within 24 hours of one another, evaluated with closed-interval semantics on both endpoints; a collision is rejected with `ERR_REPRICING_WINDOW_OVERLAP`.

Modelling a run moves it `DRAFT → MODELED` and requires that the cited standard release is in `status` `PUBLISHED`, otherwise `ERR_TARIFF_NOT_PUBLISHED`. It computes `impacted_customer_count` as the number of distinct shippers across the `ACTIVE` programs in scope and `aggregate_delta_cents` as the sum over those programs of modelled annual revenue minus baseline revenue evaluated against the new standard, and stamps `modeled_at`.

Committing a run moves it `MODELED → COMMITTED`, and a run that is not `MODELED` cannot be committed. The commit re-pins `pinned_tariff_version_id` to the run's `new_tariff_version_id` on every scoped `ACTIVE` program and recomputes each one's `baseline_revenue_cents`, `modeled_annual_revenue_cents`, `modeled_delta_pct` and `migration_recommendation` against the new standard, then stamps `committed_at`.

### 3.4. Tendering a Bill of Lading and Billing it as Declared

A `Shipper` tenders a bill of lading by supplying `customer_id`, `origin_terminal_id`, a `pro_number`, a `pickup_at` instant and a `bol_declared_total_weight_lb` of at least 1 pound — the total the shipper wrote on the bill of lading header. Tender requires that the shipper's posture is `OPEN`: a `CREDIT_HOLD` account is rejected with `ERR_CUSTOMER_CREDIT_HOLD` and a `CLOSED` account with `ERR_CUSTOMER_CLOSED`. The `pro_number` must not already exist on another shipment, or `ERR_DUPLICATE_PRO_NUMBER` is returned.

Tender pins two things, both of them permanently. `rate_program_id` is pinned to the shipper's pricing program in `status` `ACTIVE` at the moment of tender; exactly one such program exists by construction, and a shipper with none cannot tender at all, which is reported as `ERR_NO_ACTIVE_RATE_PROGRAM`. `tariff_version_id` is pinned by taking every classification release whose `status` is `PUBLISHED` or `SUPERSEDED` and whose `effective_at` is at or before the shipment's `pickup_at`, ranking those candidates by `effective_at` descending and then by `created_at` descending, and selecting the first. When no candidate exists, tender is rejected with `ERR_NO_EFFECTIVE_TARIFF`. The shipment is created with `class_status` `DECLARED` and `billing_status` `UNBILLED`, with `line_count` and `declared_total_weight_lb` at 0, with `measured_total_weight_lb` and `weight_variance_pct` null, `reweigh_required` false, `declared_vs_found_class_delta_count` at 0, `original_charge_cents`, `assessed_total_cents` and `open_notice_count` at 0, and `billed_at` null.

Each **bill-of-lading line** is then added by the same `Shipper` with a `line_no` ordinal of at least 1 and unique within the shipment, a `commodity_profile_id`, a `declared_class_code`, a `declared_weight_lb` of at least 1, a `pieces` handling-unit count of at least 1, and the three declared dimensions of one handling unit in inches — `declared_length_in`, `declared_width_in` and `declared_height_in` — each strictly greater than zero and carrying at most one decimal place. A `line_no` already present on the shipment is rejected with `ERR_DUPLICATE_LINE_NO`. The line's commodity profile must belong to the shipment's pinned `tariff_version_id`; a profile from any other release is rejected with `ERR_TARIFF_MISMATCH`. Adding a line to a shipment that has already been billed is rejected with `ERR_SHIPMENT_ALREADY_BILLED`, and adding one to a closed shipment is rejected with `ERR_INVALID_STATE_TRANSITION`. Line ordinal `line_no` is the only ordering key used whenever lines are iterated.

Cube and density are computed on the line the moment it is created. The volume of one handling unit is length multiplied by width multiplied by height, divided by 1,728 cubic inches per cubic foot, and rounded to three decimal places. That per-unit figure is then multiplied by the piece count and rounded to two decimal places, which gives `declared_cubic_ft`. `declared_density_pcf` is `declared_weight_lb` divided by `declared_cubic_ft`, rounded to two decimal places. Creating a line also recomputes the shipment's `line_count` and its `declared_total_weight_lb`, which is the sum of `declared_weight_lb` across all lines of the shipment.

Classification resolves in three ordered steps, and the same three steps run on line creation, on every dock capture that addresses the line, on acceptance of an inspection finding, on approval of an exception agreement covering the line, and on dispute resolution. **Step one** produces a base candidate. When an accepted inspection finding governs the line, the base is that finding's `found_class_code` and the provenance is `INSPECTION`; if the finding's basis was a commodity mismatch, the commodity profile used for the remaining two steps is the one the inspector named rather than the one the shipper declared. Otherwise, when the governing commodity profile has `classification_basis` `FIXED_CLASS`, the base is its `fixed_class_code` and the provenance is `FIXED_CLASS`. Otherwise, when the line has been measured, the base is the bracket lookup of the line's `measured_density_pcf` against the shipment's pinned release and the provenance is `DIMENSIONER`. Otherwise the base is the shipper's own `declared_class_code` and the provenance is `BOL_DECLARED` — the carrier bills the bill of lading until it measures the freight.

**Step two** applies a negotiated override. The system looks for an exception agreement in `status` `ACTIVE` whose `customer_id` matches the shipment's shipper, whose `commodity_profile_id` matches the profile in force after step one, and whose interval covers the shipment's `pickup_at` — meaning `effective_from` is at or before `pickup_at` and `effective_to` is strictly after it — ranked by `effective_from` descending and then `created_at` descending, taking the first. If such an agreement exists, the candidate becomes its `agreed_class_code`, and the provenance becomes `FAK` when the agreement's `agreement_type` is `FAK` and `EXCEPTION_AGREEMENT` otherwise. If no agreement applies but the shipment's pinned pricing program has `program_type` `FAK`, the candidate becomes the program's `fak_class_code` and the provenance becomes `FAK`. Otherwise the candidate is simply the step-one base.

**Step three** re-applies the characteristic floor after the override, never before it. `effective_class_code` is the greater of the step-two candidate and the governing profile's `min_class_floor`, and `class_floor_applied` is true exactly when that floor was strictly greater than the candidate. The line's `classification_source` records the provenance settled in the preceding steps and defaults to `BOL_DECLARED`; the recognized values are `BOL_DECLARED`, `FIXED_CLASS`, `DIMENSIONER`, `INSPECTION`, `EXCEPTION_AGREEMENT` and `FAK`. A line's `found_class_code` stays null until a capture or an accepted finding produces one, and `effective_class_code` is that found class when it is non-null and the declared-mode resolution otherwise.

Billing a shipment is a `PricingAnalyst` action that moves `billing_status` `UNBILLED → BILLED` and leaves `class_status` alone. It requires at least one line — a shipment with `line_count` 0 is rejected with `ERR_NO_SHIPMENT_LINES` — and requires that the shipper is not `CLOSED`. Billing a shipment a second time is rejected with `ERR_SHIPMENT_ALREADY_BILLED`.

The charge itself is built from the shipment's lines in ascending `line_no` order. Each line contributes a rating weight and a rating class. On the declared basis the rating weight is the line's `declared_weight_lb` and the rating class is the step-one-through-three resolution in declared mode; on the reclassed basis the rating weight is the line's `measured_weight_lb` where one exists and its `declared_weight_lb` otherwise, and the rating class is the line's `effective_class_code`. Adding the rating weights across all lines gives the shipment's rating weight, and one weight-break factor is derived from that shipment total and applied identically to every line. The five factors are declared in descending threshold order: 0.78 from 5,000 pounds, 0.88 from 2,000 pounds, 1.00 from 1,000 pounds, 1.15 from 500 pounds and 1.30 from nothing at all; the factor used is that of the first element whose threshold is less than or equal to the shipment rating weight. Each line's raw amount is its rating weight divided by 100, multiplied by the program's `base_rate_per_cwt_cents`, multiplied by its rating class divided by 100, multiplied by the shipment weight-break factor, multiplied by one minus the program's `discount_pct`. Those raw amounts are added across all lines, the sum is rounded once to a whole number of cents, and the result is floored at the program's `min_charge_cents`. On the declared basis this figure is stored as `original_charge_cents`, `assessed_total_cents` is set equal to it, and `billed_at` is stamped. A shipment with no lines has `original_charge_cents` of exactly 0.

Each line also carries an informational `line_charge_cents`, computed as that line's rating weight divided by 100, multiplied by `base_rate_per_cwt_cents`, multiplied by the line's `effective_class_code` divided by 100, multiplied by the shipment-level weight-break factor, multiplied by one minus `discount_pct`, and rounded on its own to a whole number of cents. Because it is rounded per line, it is explicitly not the summand used to build `original_charge_cents`; it exists so a dock clerk can see what one line is worth.

### 3.5. Measurement at the Dock: Dimensioner and Scale Capture

A terminal is registered by a `PricingAnalyst` with a `code` of three to ten characters, unique across all terminals, a display `name`, and a `calibration_interval_captures` that defaults to 250 and must be at least 1 — the number of capture events a device may record before it must be recalibrated. On registration `captures_since_calibration` is 0, `dimensioner_status` is `CALIBRATED` and `last_capture_at` is null. `dimensioner_status` is derived rather than set: it reads `CALIBRATED` while `captures_since_calibration` is strictly below `calibration_interval_captures` and flips to `OUT_OF_CALIBRATION` once the count reaches or exceeds the interval. A terminal registered with the default interval therefore takes 250 captures before its device locks out.

A `TerminalOperator` records a **capture event** against a shipment whose `origin_terminal_id` is that operator's own `X-User-ID`, supplying `shipment_id`, a `device_type`, a `measured_total_weight_lb` of at least 1 pound for the whole shipment, and a non-empty `line_measurements` array. `device_type` is `DIMENSIONER` when only cube was measured, `SCALE` when only weight was measured, or `COMBINED` when both were, and a combined device counts as two evidence items rather than one. Each element of `line_measurements` names a `line_no` together with `measured_weight_lb`, `measured_length_in`, `measured_width_in` and `measured_height_in`; every `line_no` named must exist on the captured shipment, and one that does not is rejected with `ERR_LINE_NO_MISMATCH`.

Capture requires that the shipment carries at least one line — otherwise `ERR_NO_SHIPMENT_LINES` — that the shipment's `billing_status` is not `CLOSED`, and that the capturing terminal's `dimensioner_status` is `CALIBRATED`; an out-of-calibration device is rejected with `ERR_DEVICE_OUT_OF_CALIBRATION`. The capture is stamped with `captured_at` from the logical clock, with `terminal_id` and `captured_by_user_id` both taken from the operator's `X-User-ID`, and with a `capture_sequence` equal to one more than the highest sequence previously recorded for that shipment, starting at 1. That sequence is the only ordering key used when replaying captures.

An accepted capture writes the measured dimensions and weights onto each addressed line and recomputes, for each of them, `measured_cubic_ft` and `measured_density_pcf` by the same two-step rounding used for the declared figures, then `found_class_code`, `effective_class_code`, `classification_source` and `line_charge_cents`. It recomputes the shipment's `measured_total_weight_lb` — always taken from the capture with the highest `capture_sequence`, and null before any capture — along with `weight_variance_pct`, `reweigh_required` and `declared_vs_found_class_delta_count`, the last being the number of lines whose `found_class_code` is non-null and differs from that line's `declared_class_code`. It increments the terminal's `captures_since_calibration` by one and sets `last_capture_at`.

The **variance gate** then decides whether the capture is merely informational or an exception. The absolute weight delta is the difference between the capture's `measured_total_weight_lb` and the shipment's `declared_total_weight_lb`, taken without regard to sign — and note carefully that the comparison is against the summed declared weight of the lines, not against the header figure the shipper wrote as `bol_declared_total_weight_lb`. `variance_pct` is that delta divided by `declared_total_weight_lb`, multiplied by 100, rounded to two decimal places, and it is recorded both on the capture and as the shipment's `weight_variance_pct`. `reweigh_required` becomes true only when both conditions hold together: the variance is at least 2.00 percent and the absolute delta is at least 10 pounds. The conjunction matters at both boundaries — a variance of exactly 2.00 percent on a delta of only 9 pounds does not trigger a reweigh, and a 10-pound delta that amounts to only 1.00 percent does not trigger one either. The capture's `triggered_reweigh` flag is true when this capture is what made the shipment's `reweigh_required` true. Its `triggered_reclass` flag is true when at least one line of the shipment ends up with a `found_class_code` differing from its `declared_class_code` after the capture is applied, and `reclassed_line_count` is how many such lines there are.

When neither a reweigh condition nor a class delta results, a first capture advances `class_status` `DECLARED → CAPTURED`, and a later capture holds `CAPTURED → CAPTURED` while overwriting the measured fields with the newer capture's values — re-capture is idempotent in shape but not in data, and the highest `capture_sequence` always wins.

When either a reweigh condition or a class delta does result, the shipment advances `DECLARED → RECLASS_PENDING` on a first capture, or `CAPTURED → RECLASS_PENDING` on a later one, and the full cascade fires. Alongside every effect listed above, the system creates a **correction notice** in `status` `DRAFT` with `origin` `AUTOMATED_CAPTURE` and `basis_capture_event_id` pointing at the capture that produced it, increments the shipment's `open_notice_count` by one, and therefore increments the shipment's `version` by one. The notice's `notice_type` is computed rather than supplied: `BOTH` when a reweigh condition and a class delta both hold, `RECLASS` when only a class delta holds, and `REWEIGH` when only a reweigh condition holds. A later capture may only open a notice when the shipment's `open_notice_count` is 0; a capture that would create a second open notice on a shipment that already carries one is rejected with `ERR_OPEN_NOTICE_EXISTS`.

### 3.6. Inspector Findings and their Acceptance

Automated measurement catches density and weight; it does not catch a mislabelled commodity or a stowability characteristic that only a human notices. A `FreightInspector` therefore records a finding against a single bill-of-lading line, supplying `shipment_line_id`, a `finding_basis` of `DENSITY`, `STOWABILITY`, `HANDLING`, `LIABILITY` or `COMMODITY_MISMATCH`, the `found_class_code` the inspector determined, optionally a `found_commodity_profile_id` — which is required when the basis is `COMMODITY_MISMATCH` and must be null for every other basis — optionally an `evidence_photo_count` that defaults to 0 and must not be negative, and optionally free-text `notes`. The finding is created in `status` `RECORDED` with `inspector_user_id` stamped from the acting `X-User-ID` and with `accepted_by_user_id` and `accepted_at` null. Recording requires that the target line belongs to a shipment whose `billing_status` is not `CLOSED`, and it advances the shipment's `class_status` `DECLARED → UNDER_INSPECTION` when the freight had not yet been measured, or `CAPTURED → UNDER_INSPECTION` when it had. A `RECORDED` finding changes no classification whatsoever.

Acceptance is what makes a finding bite, and it belongs to a different person. A `ClassificationAuditor` accepts a finding that is still `RECORDED`, whose `evidence_photo_count` is at least 2, and whose `inspector_user_id` differs from the auditor's own `X-User-ID`; the shipment's `billing_status` must not be `CLOSED`. A finding that is not `RECORDED` is rejected with `ERR_INVALID_STATE_TRANSITION`, an under-photographed finding with `ERR_INSUFFICIENT_EVIDENCE`, and a self-acceptance with `ERR_SOD_VIOLATION`.

Acceptance moves the finding `RECORDED → ACCEPTED` and stamps `accepted_by_user_id` and `accepted_at`. Any finding on the same line that was previously `ACCEPTED` moves `ACCEPTED → SUPERSEDED` and stops contributing to that line's classification — only the single currently-accepted finding on a line ever participates in classification, and `RECORDED` and `SUPERSEDED` findings are ignored entirely. The line's `found_class_code`, `effective_class_code`, `classification_source` — now `INSPECTION` — and `line_charge_cents` are recomputed through the three resolution steps of §3.4, and the shipment's `declared_vs_found_class_delta_count` is recomputed. The shipment's `class_status` advances `UNDER_INSPECTION → RECLASS_PENDING`.

### 3.7. Drafting, Pricing and Issuing a Correction Notice

A correction notice may arrive automatically from the dock cascade of §3.5, or a `ClassificationAuditor` may draft one by hand. A manual draft supplies `shipment_id`, a `notice_type` of `REWEIGH`, `RECLASS` or `BOTH`, the `expected_shipment_version` guard of §2.6, and optionally a `basis_capture_event_id` citing the capture used as evidence and a `supersedes_notice_id` naming a draft notice this one replaces. A manually drafted notice records `origin` `AUDITOR_MANUAL`. A manual notice must have a reclassification basis: it must cite a capture event belonging to its own shipment, or there must be an accepted inspection finding on one of that shipment's lines. A notice with neither is rejected with `ERR_NO_RECLASS_BASIS`. A shipment may carry at most one notice in `DRAFT`, `ISSUED`, `DISPUTED` or `EVIDENCE_REQUESTED`; a manual draft that would be the second is rejected with `ERR_OPEN_NOTICE_EXISTS` unless it supersedes the open draft. When `supersedes_notice_id` is supplied, the named notice moves `DRAFT → VOID`, `open_notice_count` is decremented for the voided notice and incremented for the replacement, and the shipment's `version` is incremented by one.

Two delta figures are computed at creation and refreshed on any change to the shipment's lines while the notice is still `DRAFT`. They deliberately disagree, and the disagreement is the point.

`provisional_delta_cents` is the terminal-provisional figure quoted on the dock. For each line, an amount is formed as the line's weight divided by 100, multiplied by the program's `base_rate_per_cwt_cents`, multiplied by a class divided by 100, multiplied by a weight-break factor derived from *that line's own weight* rather than from the shipment total, multiplied by one minus the program's `discount_pct`, and rounded to a whole number of cents *for that line alone*. The provisional delta is the sum over all lines of that amount computed at the reclassed rating weight and the line's `effective_class_code`, minus the same amount computed at the line's `declared_weight_lb` and its declared-mode resolution. The program's `min_charge_cents` is not applied at all in this variant.

`final_delta_cents` is the audit-final figure that will actually be billed. It is the shipment charge on the reclassed basis minus the shipment charge on the declared basis, each computed exactly as §3.4 describes — one weight-break factor derived from the shipment's aggregate rating weight, one rounding over the whole summed amount, and the minimum-charge floor applied to both legs. Because the weight break is aggregate rather than per line, because the rounding happens once rather than per line, and because the floor applies, the two variants produce different numbers on identical data.

Issuance is what freezes money and opens the shipper's clock. A `ClassificationAuditor` issues a notice that is still `DRAFT`, whose `final_delta_cents` is not exactly 0 — a zero-delta notice is rejected with `ERR_ZERO_DELTA_NOTICE` — whose `evidence_bundle_count` is at least 1 — otherwise `ERR_INSUFFICIENT_EVIDENCE` — against a shipment whose `billing_status` is `BILLED`, `REBILLED` or `CREDITED`, for a shipper whose `billing_posture` is not `CLOSED`. Issuing against an `UNBILLED` shipment is rejected with `ERR_SHIPMENT_NOT_BILLED`; issuing a notice that is not `DRAFT` is rejected with `ERR_INVALID_STATE_TRANSITION`; a closed shipper account yields `ERR_CUSTOMER_CLOSED`.

The `evidence_bundle_count` that gates issuance is a quantified tally of the supporting evidence. It counts nothing for the cited capture when `basis_capture_event_id` is null, two when the cited capture's `device_type` is `COMBINED`, and one for any other cited device; to that it adds, for each accepted inspection finding on any line of the shipment, one for the finding itself plus that finding's `evidence_photo_count`. The companion flag `uses_inspection_findings` is true whenever at least one accepted finding exists on a line of the shipment at the moment of computation.

Issuance moves the notice `DRAFT → ISSUED` and executes a cascade that spans three aggregates. On the notice itself, `applied_delta_cents` — 0 while `DRAFT` — is frozen equal to `final_delta_cents` and is never recomputed afterwards no matter what happens to the lines; `inspection_fee_cents` is frozen at $45.00 when `notice_type` is `RECLASS` or `BOTH` and at $25.00 when it is `REWEIGH`, having been 0 while `DRAFT`; and `issued_at`, `issued_by_user_id` and `dispute_deadline_at` are all stamped. On the shipment, `class_status` advances `RECLASS_PENDING → RECLASSED`, `billing_status` advances `BILLED → REBILLED`, and `assessed_total_cents` is recomputed from the ledger identity of §2.9. On the shipper account, `offender_strike_count` is incremented, both liability indices are recomputed along with `offender_tier` and `dispute_window_days`, and `education_status` flips to `REQUIRED` when the strike count reaches or exceeds `education_threshold_strikes`.

A shipment may accumulate several notices over its life, and the billing dimension cycles accordingly. A second notice issued on a shipment already `REBILLED` holds `REBILLED → REBILLED` and adds its own frozen amounts into `assessed_total_cents`; that second notice could only have been drafted while `open_notice_count` was 0. A notice issued after a credit moves the shipment `CREDITED → REBILLED` and likewise adds its frozen amounts; at issuance time that notice is the shipment's single open notice, so `open_notice_count` is 1.

The deadline stamped at issuance follows a strict ordering. The issuance cascade first recomputes both liability indices, then `offender_tier`, then the shipper's `dispute_window_days`, and only then stamps the deadline from the freshly recomputed window. Reading the pre-issuance window is a different and wrong answer whenever this very issuance changed the tier. The deadline is `issued_at` plus that base number of days, plus 7 further days for each supplement request already recorded against the notice in `supplement_request_count`. A filing is inside the window when the current logical instant is at or before `dispute_deadline_at`; the boundary instant itself counts as inside. A sweep may close the notice only when the current instant is strictly after the deadline. Because `supplement_request_count` can never exceed 2, the deadline can be pushed out at most 14 days beyond the base window. Both `issued_at` and `dispute_deadline_at` are null while a notice is `DRAFT` or `VOID`.

### 3.8. The Repeat-Offender Record: Strikes, Liability Indices, Tiers and Education

A shipper's classification-accuracy record is recomputed on every notice issuance, on every dispute resolution, and on every operations sweep. It rests on two indices that are computed from the same events but never agree, and only one of them drives anything.

A notice contributes to either index only when it has been resolved — meaning its `resolved_at` is stamped and its `status` is `UPHELD` or `PARTIALLY_OVERTURNED`. A notice that was fully overturned, voided, or is still in `DRAFT`, `ISSUED`, `DISPUTED` or `EVIDENCE_REQUESTED` contributes to neither index. Each contributing notice carries a weight of 1.0 when its `status` is `UPHELD` and 0.5 when it is `PARTIALLY_OVERTURNED`.

`liability_index_rolling` looks only at contributing notices whose `resolved_at` falls at or after 90 days before the current logical instant, and decays each of them by age. A notice's age in days is the elapsed time between its `resolved_at` and now, expressed in whole days with any partial day discarded. Its decay multiplier is one minus one percent per day of age, floored at 0.25 — so a strike stops decaying after 75 days and never contributes less than a quarter of its weight while it remains inside the window. The rolling index is the sum, across those windowed notices, of each notice's weight multiplied by its decay multiplier, rounded to two decimal places.

`liability_index_lifetime` reads the same contributing notices but applies neither of the rolling index's two reductions. There is no window filter, so a notice resolved three years ago counts exactly as much as one resolved this morning; and there is no decay multiplier, so no age is ever computed and the 0.25 floor never comes into play. The lifetime index is simply the sum, across every contributing notice of the shipper, of that notice's weight — 1.0 for each `UPHELD` and 0.5 for each `PARTIALLY_OVERTURNED` — rounded to two decimal places. The two indices therefore diverge permanently for any long-standing account, and the tier never reads the lifetime figure; the lifetime index exists purely as a reportable history.

`offender_tier` is derived from `liability_index_rolling` alone: `TIER_3` when the rolling index is at least 6.00, otherwise `TIER_2` when it is at least 3.00, otherwise `TIER_1` when it is at least 1.00, otherwise `TIER_0`. The comparisons are made against the already-rounded rolling index. `dispute_window_days` is then 30 days less 5 days for each tier step above zero — 30 days at `TIER_0`, 25 at `TIER_1`, 20 at `TIER_2` and 15 at `TIER_3` — and it is the window granted on the *next* notice issuance.

Education runs on a separate dimension. `education_threshold_strikes` starts equal to `education_strike_interval` at account creation, so a shipper on the default interval is required to attend classification education the moment its third strike lands. When an issuance pushes `offender_strike_count` to or past `education_threshold_strikes`, `education_status` moves `NONE → REQUIRED`, `education_required_at` is stamped with the logical instant, and the shipper is blocked from filing any new dispute until education completes; an attempt to file while `REQUIRED` is rejected with `ERR_EDUCATION_HOLD`. A `PricingAnalyst` records completion, which requires that `education_status` is currently `REQUIRED` — otherwise `ERR_INVALID_STATE_TRANSITION` — and moves it `REQUIRED → COMPLETED`, raises `education_threshold_strikes` to the shipper's current `offender_strike_count` plus its `education_strike_interval`, unblocks dispute filing, and increments the account's `version` by one. Education is then re-triggered every further interval of strikes: a subsequent issuance that reaches the raised threshold moves `education_status` `COMPLETED → REQUIRED` and stamps `education_required_at` again. None of this touches `billing_posture`, which evolves on its own trigger entirely.

### 3.9. Disputing a Notice: Supplement Rounds and Resolution Outcomes

A `Shipper` contests an issued notice by filing a **dispute** naming the `correction_notice_id`, a `claim_basis` of `DENSITY_RECOMPUTE`, `EXCEPTION_AGREEMENT`, `DEVICE_CALIBRATION` or `EVIDENCE_INSUFFICIENT`, an `evidence_doc_count` of at least 1 document, and optionally a `claimed_class_code` asserting what the shipper believes the correct class to be. Filing requires that the notice's `status` is `ISSUED` — a notice in any other status is rejected with `ERR_NOTICE_NOT_DISPUTABLE` — that the current logical instant is at or before the notice's `dispute_deadline_at`, or `ERR_DISPUTE_WINDOW_CLOSED`, that the shipper's `education_status` is not `REQUIRED`, or `ERR_EDUCATION_HOLD`, and that the notice's `dispute_round_count` is strictly below 3, or `ERR_MAX_DISPUTE_ROUNDS`. A filing with no attached document is rejected with `ERR_INSUFFICIENT_EVIDENCE`.

Filing creates the dispute in `status` `OPEN` with `round_no` 1, stamps `filed_by_customer_id` from the acting `X-User-ID` and `filed_at` from the logical clock, leaves `reviewer_user_id`, `outcome`, `outcome_class_code` and `resolved_at` null, and moves the notice `ISSUED → DISPUTED` while incrementing its `dispute_round_count`. A dispute's `round_no` always equals its notice's `dispute_round_count` after the filing or supplement that produced it.

A `DisputeReviewer` who did not issue the notice may ask for more evidence, optionally attaching a `reason_note`. The request requires that the dispute is `OPEN` or `SUPPLEMENTED` and that the notice's `supplement_request_count` is strictly below 2, or `ERR_MAX_DISPUTE_ROUNDS`. It moves the dispute `OPEN → SUPPLEMENT_REQUESTED` or `SUPPLEMENTED → SUPPLEMENT_REQUESTED`, stamps `reviewer_user_id` with the reviewer's `X-User-ID`, moves the notice `DISPUTED → EVIDENCE_REQUESTED`, increments `supplement_request_count` and extends `dispute_deadline_at` by a further 7 days.

The shipper who filed the dispute answers with an `additional_doc_count`. Supplementing requires that the dispute is `SUPPLEMENT_REQUESTED` — otherwise `ERR_INVALID_STATE_TRANSITION` — that the acting `X-User-ID` equals the dispute's `filed_by_customer_id`, and that the notice's `dispute_round_count` is strictly below 3. It moves the dispute `SUPPLEMENT_REQUESTED → SUPPLEMENTED`, adds `additional_doc_count` to the dispute's `evidence_doc_count`, increments the dispute's `round_no`, and returns the notice `EVIDENCE_REQUESTED → DISPUTED` while incrementing its `dispute_round_count`. The reviewer may then request another supplement, so the negotiation cycles `DISPUTED → EVIDENCE_REQUESTED → DISPUTED` until either the two-request ceiling or the three-round ceiling binds.

Resolution is a three-way branch, restricted to a `DisputeReviewer` who is not the notice's `issued_by_user_id`. The reviewer supplies an `outcome` of `UPHELD_CARRIER`, `PARTIAL` or `OVERTURNED`, optionally a `resolution_note`, and an `outcome_class_code` that must be present when the outcome is `PARTIAL` and must be absent for the other two. A `PARTIAL` outcome's `outcome_class_code` must also differ from the class the notice already assessed on every reclassed line. Any violation of these shape rules is rejected with `ERR_INVALID_PARTIAL_OUTCOME`. A dispute may be resolved out of any of its three non-terminal states — `OPEN → RESOLVED` when the reviewer never asked for more, `SUPPLEMENT_REQUESTED → RESOLVED` when the reviewer decides without waiting for the shipper's answer, and `SUPPLEMENTED → RESOLVED` after the shipper answered — and in every case `outcome`, `outcome_class_code`, `reviewer_user_id` and `resolved_at` are recorded. Resolving an already-`RESOLVED` dispute is rejected with `ERR_INVALID_STATE_TRANSITION`.

Each branch drives a different set of effects, and none of the three may borrow another's.

On `UPHELD_CARRIER`, the notice moves `DISPUTED → UPHELD` or `EVIDENCE_REQUESTED → UPHELD` and its `resolved_at` is stamped. Classification is untouched on every line, `applied_delta_cents` and `inspection_fee_cents` keep the values frozen at issuance, `assessed_total_cents` does not change, and no credit memo is created at all. The shipment's `class_status` holds `RECLASSED → RECLASSED` and its `billing_status` does not move. The shipper's `offender_strike_count` is neither incremented nor decremented, but the liability indices, `offender_tier` and `dispute_window_days` are recomputed, because the notice has just become a contributing resolved strike at full weight.

On `PARTIAL`, the notice moves `DISPUTED → PARTIALLY_OVERTURNED`, `resolved_at` is stamped, and the shipment is re-rated with `outcome_class_code` substituted on every line the notice had reclassed, with each affected line's charge recomputed. A credit memo is created with `reason` `PARTIAL_OVERTURN`, the shipment's `billing_status` moves `BILLED → CREDITED` or `REBILLED → CREDITED`, `assessed_total_cents` is recomputed, `class_status` holds `RECLASSED → RECLASSED`, and the shipper's indices, tier and window are recomputed — the notice now contributing at half weight. The strike count is not decremented.

On `OVERTURNED`, the notice moves `DISPUTED → OVERTURNED` and `resolved_at` is stamped. Every line of the shipment reverts to its declared classification: `found_class_code` returns to null and `classification_source` returns to `BOL_DECLARED`. A credit memo is created with `reason` `FULL_OVERTURN`, the shipment's `billing_status` moves `BILLED → CREDITED` or `REBILLED → CREDITED` and `assessed_total_cents` is recomputed, the shipment's `class_status` moves backward `RECLASSED → CAPTURED` — the reclassification is undone and the shipment returns to the measured-but-unreclassed state — and the shipper's `offender_strike_count` is decremented before the indices, tier and window are recomputed. A fully overturned notice contributes to neither index thereafter.

Whenever an outcome of `PARTIAL` or `OVERTURNED` produces a credit, the amount is allocated across three ordered buckets, each filled completely before the next is considered, and any overflow past the third bucket's cap is dropped rather than reallocated. Bucket one is freight. On a full overturn, `freight_credit_cents` is the notice's frozen `applied_delta_cents` in full. On a partial overturn, it is the shipment charge on the reclassed basis at the frozen classes, minus the shipment charge on the reclassed basis with `outcome_class_code` substituted on every line whose `effective_class_code` the notice had raised. Bucket two is the accessorial fee: `fee_credit_cents` is the notice's frozen `inspection_fee_cents` on a full overturn and exactly 0 on a partial one, since only a complete reversal refunds the inspection fee. Bucket three is goodwill interest: the uncapped figure is `freight_credit_cents` multiplied by one half of one percent per dispute round, multiplied by the notice's `dispute_round_count`, rounded to a whole number of cents, and `interest_credit_cents` is the lesser of that figure and a cap of $2.50. The memo's `amount_cents` is the three buckets added together, and `issued_at` is stamped with the instant the resolution cascade created it. The memo records `correction_notice_id` and `customer_id` so the credit is traceable to both the notice it reverses and the shipper it benefits, and the notice's `credited_total_cents` is the sum of `amount_cents` across every memo issued against it. Only buckets one and two enter the shipment ledger identity of §2.9; the interest bucket sits outside it deliberately, which is why a full overturn returns `assessed_total_cents` to exactly `original_charge_cents`. Credit memos are never created directly by a client — the resolution cascade is their only origin, and the memo listing is their only discovery channel.

### 3.10. Sweeping Unchallenged Notices and Closing the Shipment

Not every notice is contested. An operations sweep, restricted to a `PricingAnalyst`, walks every notice in `status` `ISSUED` whose `dispute_deadline_at` is strictly in the past relative to the current logical instant and against which no dispute exists at all, and moves each one `ISSUED → UPHELD` with `resolved_at` stamped at the sweep instant. This is a branch join: an unchallenged notice reaches the same terminal state, and the same full-weight contribution to the liability indices, as one that survived review. The sweep then recomputes the affected shippers' `liability_index_rolling`, `liability_index_lifetime`, `offender_tier` and `dispute_window_days`. It answers with a `swept_count` and the list of affected notice identifiers as `upheld_notice_ids`.

Closing a shipment is the last act on it, performed by a `PricingAnalyst`. It requires that the shipment's `open_notice_count` is 0 and that its `billing_status` is `BILLED`, `REBILLED` or `CREDITED`; closing a shipment that is still `UNBILLED` is rejected with `ERR_SHIPMENT_NOT_BILLED`. Closure advances both dimensions at once. On the money dimension it performs `BILLED → CLOSED`, `REBILLED → CLOSED` or `CREDITED → CLOSED` according to where the shipment stood. On the classification dimension it performs `DECLARED → CLASS_CONFIRMED` for freight that was never measured, `CAPTURED → CLASS_CONFIRMED` for freight that was measured without correction, or `RECLASSED → CLASS_CONFIRMED` for freight that was corrected. Both `CLOSED` and `CLASS_CONFIRMED` are terminal — a closed shipment accepts no further lines, no further captures and no further findings — and its money is frozen at whatever the ledger identity last produced.

## 4. Endpoint Definitions

Operations that bring a new resource into existence — registering a terminal or a shipper, drafting a standard release, a commodity profile, a pricing program or an exception agreement, tendering a bill of lading, adding a line, recording a capture or a finding, drafting a correction notice, filing a dispute, or opening a repricing run — answer with `201 Created`. Every operation that advances or modifies an existing resource, and every read, answers with `200 OK`. Errors carry the HTTP status listed in §5 for the returned `error_id`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Move the server's logical clock to a supplied instant | PricingAnalyst |
| POST | `/ltl/terminals` | Register a terminal with its dimensioner calibration interval | PricingAnalyst |
| GET | `/ltl/terminals/{id}` | Read one terminal including its live calibration counters | PricingAnalyst, TerminalOperator, ClassificationAuditor |
| POST | `/ltl/customers` | Register a shipper account | PricingAnalyst |
| GET | `/ltl/customers/{id}` | Read one shipper account including both liability indices, tier and dispute window | PricingAnalyst, ClassificationAuditor, DisputeReviewer, Shipper |
| POST | `/ltl/customers/{id}/posture` | Move the shipper's credit posture | PricingAnalyst |
| POST | `/ltl/customers/{id}/education/complete` | Record completion of mandatory classification education | PricingAnalyst |
| POST | `/ltl/tariff-versions` | Draft a classification standard release with its density bracket table | PricingAnalyst |
| GET | `/ltl/tariff-versions/{id}` | Read one classification standard release | PricingAnalyst, ClassificationAuditor |
| GET | `/ltl/tariff-versions` | List classification standard releases | PricingAnalyst, ClassificationAuditor |
| POST | `/ltl/tariff-versions/{id}/publish` | Publish a drafted standard, superseding the previous newest published one | PricingAnalyst |
| POST | `/ltl/commodity-profiles` | Add a commodity item to a drafted standard | PricingAnalyst |
| GET | `/ltl/commodity-profiles/{id}` | Read one commodity profile including its computed class floor | PricingAnalyst, ClassificationAuditor, FreightInspector, Shipper |
| GET | `/ltl/commodity-profiles` | List commodity profiles | PricingAnalyst, ClassificationAuditor, FreightInspector, Shipper |
| POST | `/ltl/rate-programs` | Draft a pricing program for a shipper | PricingAnalyst |
| GET | `/ltl/rate-programs/{id}` | Read one pricing program including its modelled migration impact | PricingAnalyst, ClassificationAuditor |
| GET | `/ltl/rate-programs` | List pricing programs | PricingAnalyst, ClassificationAuditor |
| POST | `/ltl/rate-programs/{id}/approve` | Approve a program: pin the newest published standard and run the impact model | PricingAnalyst |
| POST | `/ltl/rate-programs/{id}/activate` | Activate an approved program, retiring the shipper's previous active program | PricingAnalyst |
| POST | `/ltl/exception-agreements` | Negotiate an exception class or freight-all-kinds arrangement for one commodity | PricingAnalyst |
| GET | `/ltl/exception-agreements/{id}` | Read one negotiated exception agreement | PricingAnalyst, ClassificationAuditor |
| GET | `/ltl/exception-agreements` | List exception agreements | PricingAnalyst, ClassificationAuditor |
| POST | `/ltl/exception-agreements/{id}/approve` | Approve a pending exception agreement | PricingAnalyst |
| POST | `/ltl/shipments` | Tender a bill of lading, pinning the active program and the effective standard | Shipper |
| GET | `/ltl/shipments/{id}` | Read one shipment including both status dimensions and the money fields | Shipper, PricingAnalyst, ClassificationAuditor, TerminalOperator, DisputeReviewer, FreightInspector |
| GET | `/ltl/shipments` | List shipments | Shipper, PricingAnalyst, ClassificationAuditor, TerminalOperator, DisputeReviewer, FreightInspector |
| POST | `/ltl/shipments/{id}/lines` | Add a bill-of-lading line with its declared class, weight, pieces and dimensions | Shipper |
| GET | `/ltl/shipment-lines/{id}` | Read one bill-of-lading line including declared and measured cube, density and class | Shipper, PricingAnalyst, ClassificationAuditor, FreightInspector, TerminalOperator, DisputeReviewer |
| GET | `/ltl/shipment-lines` | List bill-of-lading lines | Shipper, PricingAnalyst, ClassificationAuditor, FreightInspector, TerminalOperator, DisputeReviewer |
| POST | `/ltl/shipments/{id}/bill` | Bill the shipment on the declared basis | PricingAnalyst |
| POST | `/ltl/shipments/{id}/close` | Close the shipment, confirming its classification and freezing its ledger | PricingAnalyst |
| POST | `/ltl/capture-events` | Record a dimensioner and/or scale capture, driving automated reweigh and reclass | TerminalOperator |
| GET | `/ltl/capture-events/{id}` | Read one capture event including its variance and reclass outcome | TerminalOperator, ClassificationAuditor, PricingAnalyst, DisputeReviewer |
| GET | `/ltl/capture-events` | List capture events | TerminalOperator, ClassificationAuditor, PricingAnalyst, DisputeReviewer |
| POST | `/ltl/inspection-findings` | Record an inspector's classification finding against one line | FreightInspector |
| GET | `/ltl/inspection-findings/{id}` | Read one inspection finding | FreightInspector, ClassificationAuditor, DisputeReviewer |
| GET | `/ltl/inspection-findings` | List inspection findings | FreightInspector, ClassificationAuditor, DisputeReviewer |
| POST | `/ltl/inspection-findings/{id}/accept` | Accept a finding into the classification of record | ClassificationAuditor |
| POST | `/ltl/correction-notices` | Draft a correction notice manually | ClassificationAuditor |
| GET | `/ltl/correction-notices/{id}` | Read one correction notice including both delta variants and the dispute deadline | ClassificationAuditor, DisputeReviewer, Shipper, PricingAnalyst |
| GET | `/ltl/correction-notices` | List correction notices | ClassificationAuditor, DisputeReviewer, Shipper, PricingAnalyst |
| POST | `/ltl/correction-notices/{id}/issue` | Issue the notice, freezing the billed amounts and opening the dispute window | ClassificationAuditor |
| POST | `/ltl/notice-sweeps` | Close every issued notice whose dispute window elapsed unchallenged | PricingAnalyst |
| POST | `/ltl/disputes` | File a shipper dispute against an issued notice inside its window | Shipper |
| GET | `/ltl/disputes/{id}` | Read one dispute including its round number and outcome | Shipper, DisputeReviewer, ClassificationAuditor, PricingAnalyst |
| GET | `/ltl/disputes` | List disputes | Shipper, DisputeReviewer, ClassificationAuditor, PricingAnalyst |
| POST | `/ltl/disputes/{id}/request-supplement` | Ask the shipper for more evidence, extending the dispute window | DisputeReviewer |
| POST | `/ltl/disputes/{id}/supplement` | Supply the requested supplemental evidence, opening another review round | Shipper |
| POST | `/ltl/disputes/{id}/resolve` | Resolve the dispute, driving the credit cascade | DisputeReviewer |
| GET | `/ltl/credit-memos/{id}` | Read one credit memo including the three waterfall buckets | PricingAnalyst, Shipper, DisputeReviewer |
| GET | `/ltl/credit-memos` | List credit memos | PricingAnalyst, Shipper, DisputeReviewer |
| POST | `/ltl/repricing-runs` | Open a repricing checkpoint for a published standard over a sample window | PricingAnalyst |
| GET | `/ltl/repricing-runs/{id}` | Read one repricing run including its aggregate impact | PricingAnalyst |
| GET | `/ltl/repricing-runs` | List repricing runs | PricingAnalyst |
| POST | `/ltl/repricing-runs/{id}/model` | Model the impact of adopting the new standard across scoped active programs | PricingAnalyst |
| POST | `/ltl/repricing-runs/{id}/commit` | Commit the repricing, re-pinning every scoped active program | PricingAnalyst |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_TERMINAL_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_TARIFF_VERSION_NOT_FOUND` | 404 |
| `ERR_COMMODITY_PROFILE_NOT_FOUND` | 404 |
| `ERR_RATE_PROGRAM_NOT_FOUND` | 404 |
| `ERR_EXCEPTION_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_LINE_NOT_FOUND` | 404 |
| `ERR_CAPTURE_EVENT_NOT_FOUND` | 404 |
| `ERR_INSPECTION_FINDING_NOT_FOUND` | 404 |
| `ERR_CORRECTION_NOTICE_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_CREDIT_MEMO_NOT_FOUND` | 404 |
| `ERR_REPRICING_RUN_NOT_FOUND` | 404 |
| `ERR_INVALID_CLASS_CODE` | 422 |
| `ERR_INVALID_DIMENSIONS` | 422 |
| `ERR_INVALID_DENSITY_BREAKS` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_STALE_CUSTOMER_VERSION` | 412 |
| `ERR_STALE_SHIPMENT_VERSION` | 412 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_NOTICE_NOT_DISPUTABLE` | 409 |
| `ERR_SHIPMENT_NOT_BILLED` | 409 |
| `ERR_SHIPMENT_ALREADY_BILLED` | 409 |
| `ERR_OPEN_NOTICE_EXISTS` | 409 |
| `ERR_DEVICE_OUT_OF_CALIBRATION` | 409 |
| `ERR_CUSTOMER_CREDIT_HOLD` | 409 |
| `ERR_CUSTOMER_CLOSED` | 409 |
| `ERR_EDUCATION_HOLD` | 409 |
| `ERR_TARIFF_NOT_PUBLISHED` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_INSUFFICIENT_EVIDENCE` | 422 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 |
| `ERR_TARIFF_EFFECTIVE_CONFLICT` | 409 |
| `ERR_DUPLICATE_PRO_NUMBER` | 409 |
| `ERR_DUPLICATE_LINE_NO` | 409 |
| `ERR_EXCEPTION_OVERLAP` | 409 |
| `ERR_REPRICING_WINDOW_OVERLAP` | 409 |
| `ERR_MAX_DISPUTE_ROUNDS` | 409 |
| `ERR_LINE_NO_MISMATCH` | 422 |
| `ERR_TARIFF_MISMATCH` | 422 |
| `ERR_NO_RECLASS_BASIS` | 422 |
| `ERR_INVALID_PARTIAL_OUTCOME` | 422 |
| `ERR_NO_ACTIVE_RATE_PROGRAM` | 422 |
| `ERR_NO_EFFECTIVE_TARIFF` | 422 |
| `ERR_ZERO_DELTA_NOTICE` | 422 |
| `ERR_NO_SHIPMENT_LINES` | 422 |
