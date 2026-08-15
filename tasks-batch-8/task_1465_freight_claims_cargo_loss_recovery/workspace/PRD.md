# Freight Claims & Cargo Loss Recovery API — Product Requirements Document

## 1. Introduction

A shipper's claims department lives and dies by two clocks and a ledger. The clocks are statutory: under the Carmack Amendment framework, a carrier must acknowledge a cargo claim within a contracted acknowledgment window, and a claimant's right to civil action evaporates if the claim is not filed within the filing window. The ledger is financial: every claim carries a computed carrier liability, a salvage credit, an open reserve, and a negotiated settlement, and every dollar of leakage — an overpaid settlement, a missed salvage offset, a third party never pursued — comes straight out of margin. When claims are tracked in spreadsheets, deadlines slip, adjusters approve their own assessments, and nobody can answer the simple question of which carriers and lanes are bleeding.

This document specifies the Freight Claims & Cargo Loss Recovery API, the system of record for that department. It governs the full arc of a cargo claim — intake and documentation, carrier-liability determination under four limitation-of-liability models, salvage disposition and credit, settlement negotiation under tiered authority, decline and appeal, subrogation against responsible third parties, and claim-ratio analytics by carrier and lane. It is written for the engineers who will build the API; Section 2 fixes the system-wide contracts, Section 3 narrates the business workflows in which those contracts come alive, Section 4 enumerates the endpoints, and Section 5 catalogs the error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted to invoke the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes seven working roles plus one read-only pseudo-role, spelled exactly as follows: `PlatformAdmin` (test-driving operations: the logical clock and the business calendar), `ClaimsClerk` (intake: registers shipments, opens claims, attaches documents, submits and withdraws claims), `ClaimsAdjuster` (acknowledgment, document verification, liability assessment, first-line settlement authority, decline, and appeal intake), `ClaimsManager` (carrier and lane administration, assessment approval, appeal escalation and decision, settlement acceptance and rejection, claim closure), `SalvageCoordinator` (scheduling, executing, and cancelling salvage dispositions), `SubrogationSpecialist` (third-party recovery), and `FinanceController` (reserves, top-tier settlement acceptance, carrier termination). The pseudo-role `Any` denotes that every authenticated role shares read access to all resources.

For each of these roles — `PlatformAdmin`, `ClaimsClerk`, `ClaimsAdjuster`, `ClaimsManager`, `SalvageCoordinator`, `SubrogationSpecialist`, `FinanceController`, and `Any` — `X-User-ID` is an opaque operator identifier that is not tied to the `id` of any persisted entity. The server records it where a workflow requires an actor of record — for example as `assessed_by_user_id` on a liability assessment, `opened_by_user_id` on an appeal, `approved_by_user_id` on a settlement, `posted_by_user_id` on a reserve, or `actor_user_id` on an event — but it never compares `X-User-ID` against any entity's `id`. The only comparisons the system makes between operator identifiers are the segregation-of-duties checks described in §3, which compare two recorded operator ids against each other.

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

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, list endpoints accept resource-specific filters: carriers filter by `status`; lanes filter by `status`; carrier–lane assignments filter by `carrier_id` and `lane_id`; shipments filter by `carrier_id`, `lane_id`, and `status`; claims filter by `carrier_id`, `lane_id`, `shipment_id`, `filing_status`, `payment_status`, and `liability_assessment_id`; documents filter by `verification_status` and `document_kind`; salvage dispositions, appeals, settlements, subrogation cases, and reserves each filter by `state`; the claim event log filters by `event_kind`; calendar rows filter by `day_kind`; the carrier claim-ratio analytic filters by `carrier_id` and a `window` selector; and the lane claim-ratio analytic filters by `lane_id`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations driven by server-side cascades.

Two resources are deliberately lighter. A `CarrierLaneAssignment` and a `ClaimEvent` each carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, because assignments are immutable once declared and events are append-only.

Any change to a resource's own fields — including derived counters and recomputed ratios on a `Carrier`, `Lane`, or `Claim` — counts as a mutation of that resource and therefore refreshes its `updated_at` and increments its `version`. A claim additionally surfaces `concurrency_token`, an integer that mirrors its `version` and exists so that assessment and settlement writers reason over the same optimistic-concurrency value described in §2.6.

### 2.5. Money, Precision, and Rounding

All monetary amounts in this API — declared values, claimed amounts, liability figures, salvage proceeds and credits, reserves, settlements, and recovery targets — are integer cents. No floating-point money appears anywhere in request or response bodies. Three rounding disciplines apply, each stated where its calculation lives and summarized here: the limitation-of-liability pipeline rounds down to a whole cent (floor) at each multiplication step; basis-point analytics round half-up to a whole basis point against a denominator of 10,000; and the reserve-sizing guidance rounds half-up exactly once, at its final step. Derived fields such as a claim's `net_exposure_cents` are never negative — a floor of zero is applied wherever a subtraction could otherwise carry the figure below zero.

### 2.6. Optimistic Concurrency Control on Claim Writes

Three write operations against a claim require the client to prove it has observed the claim's current state. Each request body must carry `expected_claim_version`, set to the value of the claim's `version` the client last read. If that value does not match the claim's current `version` — because another writer has since advanced it, for example by posting an assessment, executing a salvage credit, or posting a reserve, all of which legitimately alter the claim's exposure figures and bump its version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The three guarded operations are: extending a settlement offer on a claim under review, declining a claim under review, and opening an appeal on a declined claim. In the appeal case the hazard is concrete: the claim's `appeal_round` counter may have been advanced by another appeal, changing eligibility. No endpoint other than these three takes a version field; all other writes proceed without an optimistic-concurrency check.

### 2.7. The Logical Clock and Scheduled Transitions

All server-side time in this system comes from a logical clock, never from the wall clock. Before any operator sets it, the logical clock reads 2026-08-01T00:00:00Z. A `PlatformAdmin` advances it through a test-driving capability that accepts a `to_iso8601` instant and echoes the resulting `now_iso8601`; every server-stamped timestamp in the system — filing receipts, posting times, event times, release times — is taken from this clock.

Advancing the clock drives four families of scheduled behavior. First, acknowledgment lateness: a daily sweep flags any claim whose `acknowledgment_due_at` has passed without a recorded acknowledgment by setting `acknowledgment_late` and appending an `ACK_LATE_FLAGGED` event. Second, time-barring: a claim still `SUBMITTED` once the logical time passes its `filing_deadline_at` transitions to `TIME_BARRED`, and a claim still `ACKNOWLEDGED` once the logical time passes its `filing_deadline_at` by more than 365 days likewise transitions to `TIME_BARRED`. Third, offer expiry: a settlement still `OFFERED` more than 14 days after its creation transitions to `EXPIRED` and returns its claim to `UNDER_REVIEW`. Fourth, salvage execution: a disposition whose `scheduled_at` has been reached is executed by the system exactly as if a coordinator had executed it by hand. The business calendar — rows declared by a `PlatformAdmin` giving each `calendar_date`, an `is_business_day` flag, and a `day_kind` of `BUSINESS`, `WEEKEND`, or `HOLIDAY` — is maintained as reference data for business-day deadline awareness; the statutory acknowledgment and filing windows themselves are measured in calendar days.

### 2.8. Nested Resource Retrieval

Requests that target nested resources validate path identifiers strictly left to right, and the request is rejected with a 404 the moment the first identifier fails to resolve. A request aimed at a document under a claim that does not exist is rejected with `ERR_CLAIM_NOT_FOUND` before the document id is ever examined. The resource-specific identifiers are: `ERR_CARRIER_NOT_FOUND`, `ERR_LANE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SALVAGE_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_SUBROGATION_NOT_FOUND`, and `ERR_RESERVE_NOT_FOUND` — each HTTP 404, each naming exactly the path segment that failed to resolve.

### 2.9. Validation Order

Before any business rule runs, two generic shape checks apply: a malformed payload or a field of the wrong type is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and an enum field receiving a value outside its declared set is rejected with `ERR_INVALID_ENUM` (HTTP 400). A related generic range check rejects an `effective_to` that is not later than its `effective_from`, a `delivery_date` earlier than its `ship_date`, or a `scheduled_at` that is not in the future with `ERR_INVALID_TEMPORAL_RANGE` (HTTP 400).

When several validations could apply to the same request, they are evaluated in a fixed priority order, and the earliest failure is the one reported. The order is: (1) header presence and well-formedness, producing `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role authorization, producing `ERR_INSUFFICIENT_PERMISSIONS`; (3) left-to-right existence of every path identifier, producing the resource-specific 404 of §2.8; (4) whether the parent claim's state admits the requested child operation at all, producing `ERR_CLAIM_INVALID_STATE` (HTTP 409); (5) optimistic concurrency, producing `ERR_STALE_VERSION`; (6) segregation of duties, producing `ERR_SEGREGATION_OF_DUTIES_VIOLATION`; (7) business temporal rules — the filing deadline at submit, a salvage execution time in the future at scheduling, and a delivery date no earlier than the ship date at shipment registration — producing `ERR_FILING_DEADLINE_PASSED` (HTTP 422); (8) required-document presence at submit, producing `ERR_REQUIRED_DOCUMENT_MISSING` (HTTP 422); (9) document verification completeness at assessment, producing `ERR_DOCUMENTS_NOT_VERIFIED` (HTTP 422); (10) fiscal amount checks, producing `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE` (HTTP 422); (11) reserve coverage at settlement acceptance, producing `ERR_RESERVE_INSUFFICIENT` (HTTP 402); (12) settlement authority tier, producing `ERR_AUTHORITY_TIER_INSUFFICIENT` (HTTP 403); (13) appeal-round eligibility, producing `ERR_APPEAL_ROUND_EXHAUSTED` (HTTP 409); (14) claim-opening referential gating, producing `ERR_SHIPMENT_NOT_DELIVERED` (HTTP 409); (15) uniqueness of natural keys, producing `ERR_DUPLICATE_KEY` (HTTP 409); (16) the indemnity-first gate on subrogation, producing `ERR_CLAIM_NOT_PAID` (HTTP 409); and (17) the open-exposure gate on carrier and lane lifecycle actions, producing `ERR_OPEN_EXPOSURE_EXISTS` (HTTP 409). Because claim state is checked before optimistic concurrency, a claim in the wrong state reports `ERR_CLAIM_INVALID_STATE` even when the request also carries a stale version; because segregation of duties outranks fiscal checks, a forbidden same-user approval surfaces as `ERR_SEGREGATION_OF_DUTIES_VIOLATION` rather than being masked by a later amount check.

### 2.10. The Claim Event Log

Every claim carries an append-only audit log of `ClaimEvent` records. Each event records its `claim_id`, an `event_kind`, the `actor_user_id` of whoever triggered it (the literal value `system` for scheduler-driven transitions), an `event_at` timestamp taken from the logical clock, and a `payload_json` snapshot holding event-specific detail. The declared event kinds are `FILED`, `ACKNOWLEDGED`, `ASSESSED`, `OFFER_EXTENDED`, `OFFER_ACCEPTED`, `OFFER_REJECTED`, `DECLINED`, `APPEAL_OPENED`, `APPEAL_DECIDED`, `SALVAGE_POSTED`, `RESERVE_POSTED`, `RESERVE_RELEASED`, `PAID_OUT`, `SUBROGATION_OPENED`, `SUBROGATION_RECOVERY`, `WITHDRAWN`, `TIME_BARRED`, and `ACK_LATE_FLAGGED`; each is recorded when its namesake business action occurs, as narrated in §3. Events are never updated or deleted, and as noted in §2.4 a `ClaimEvent` carries neither `updated_at` nor `version`.

## 3. Business Logic & Workflows

### 3.1. Carrier and Lane Administration

A `ClaimsManager` onboards a carrier by supplying its `scac_code` — the Standard Carrier Alpha Code, unique across carriers, with duplicates rejected by `ERR_DUPLICATE_KEY` — along with its `legal_name` and its `liability_model`, one of `FULL_VALUE`, `RELEASED_RATE`, `PER_PACKAGE`, or `PER_POUND`. The liability model selects which cap fields are meaningful: `released_rate_cents_per_lb` applies only under `RELEASED_RATE`, `per_package_cap_cents` only under `PER_PACKAGE`, and `per_pound_cap_cents` only under `PER_POUND`. Registration also fixes the carrier's `max_auto_settle_cents`, the largest settlement an adjuster may see flow through without higher-tier authority, and its two Carmack windows: `carmack_acknowledgment_days`, defaulting to 30 calendar days, and `carmack_filing_days`, defaulting to 270 calendar days — a statutory floor that a contract may lengthen but never shorten. A freshly registered carrier is `ACTIVE` with `claims_filed_count`, `claims_paid_count`, and `claim_ratio_bp` all zero.

Carrier lifecycle actions are guarded by open exposure. A `ClaimsManager` may suspend an `ACTIVE` carrier only while no claim assigned to that carrier carries an open reserve and sits in a non-terminal filing state; otherwise the attempt fails with `ERR_OPEN_EXPOSURE_EXISTS`, and the carrier becomes `SUSPENDED`. Reinstatement returns a `SUSPENDED` carrier to `ACTIVE`. Termination is a `FinanceController` action, permitted only from `SUSPENDED`, and only while no claim of that carrier remains in any non-terminal filing state — again `ERR_OPEN_EXPOSURE_EXISTS` on violation — after which the carrier is `TERMINATED`, a terminal state. Each of these three actions increments the carrier's `version`.

Lanes are simpler. A `ClaimsManager` declares a lane with its `origin_zip3`, `destination_zip3`, and `baseline_claim_ratio_bp` — the industry-baseline claim ratio for that lane, against which the lane's live ratio is later compared. A new lane is `ACTIVE` with `shipments_count`, `claims_count`, and `lane_claim_ratio_bp` all zero. Retiring a lane, also a `ClaimsManager` action, is refused with `ERR_OPEN_EXPOSURE_EXISTS` while any shipment on the lane is in `CLAIMED` status; a retired lane is `RETIRED`, which is terminal, and the retirement increments the lane's `version`.

Between carriers and lanes sits the `CarrierLaneAssignment`, declared by a `ClaimsManager` with a `carrier_id`, a `lane_id`, a `contracted_discount_pct` between 0 and 100, and an effectiveness window running from `effective_from` (inclusive) to `effective_to` (exclusive); an `effective_to` that does not fall after `effective_from` is rejected with `ERR_INVALID_TEMPORAL_RANGE`. The triple of carrier, lane, and `effective_from` must be unique — a repeat is `ERR_DUPLICATE_KEY`. The assignment is what lets a negotiated discount reach the liability pipeline of §3.4, and per §2.4 it carries no `updated_at` or `version`.

### 3.2. Shipment Registration and Claim Intake

Everything begins with a delivered shipment. A `ClaimsClerk` registers it with its `bol_number` — unique across shipments, duplicates drawing `ERR_DUPLICATE_KEY` — the `carrier_id` and `lane_id` it moved under, the `ship_date` and `delivery_date` (delivery must not precede shipment, else `ERR_INVALID_TEMPORAL_RANGE`), the shipper-declared `declared_value_cents`, the `total_weight_lbs` (greater than zero), the `package_count` (greater than zero), a `commodity_class` of `GENERAL`, `FRAGILE`, `PERISHABLE`, `HIGH_VALUE`, or `HAZMAT`, and an optional `is_concealed_damage` flag that defaults to false and marks damage discovered after delivery without notation on the receipt. Registration sets the shipment's `status` to `DELIVERED` and increments the lane's `shipments_count`, which in turn causes `lane_claim_ratio_bp` to be recomputed as described in §3.9.

Against a delivered shipment, a `ClaimsClerk` opens a claim with a payload carrying the `shipment_id`, a `claim_type` of `LOSS`, `DAMAGE`, `SHORTAGE`, `CONCEALED_DAMAGE`, or `DELAY`, and a `claimed_amount_cents` that must be greater than zero and no more than the shipment's `declared_value_cents` — an overreach is `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE`. Four referential gates must all hold at opening: the shipment is in `DELIVERED` status, the carrier is `ACTIVE`, the lane is `ACTIVE`, and a carrier–lane assignment whose effectiveness window covers the shipment's `ship_date` exists; failure of any of them is reported as `ERR_SHIPMENT_NOT_DELIVERED`. A new claim opens in `DRAFT` with `payment_status` `UNPAID` — the payment dimension's declared values are `UNPAID`, `PARTIAL`, `PAID_IN_FULL`, and `WAIVED`, with the middle two reached only through settlement acceptance as §3.6 describes — an `appeal_round` of zero, null `acknowledged_at`, `settlement_amount_cents`, and `liability_assessment_id`, and zeroed `computed_liability_cents`, `salvage_credit_cents`, `net_exposure_cents`, and `reserve_amount_cents`. The claim denormalizes `carrier_id` and `lane_id` from its shipment at creation so that analytics never have to walk back through the shipment.

A draft claim accumulates evidence. A `ClaimsClerk` attaches documents, each with a `document_kind` of `BOL`, `COMMERCIAL_INVOICE`, `PHOTO`, `DELIVERY_RECEIPT`, `INSPECTION_REPORT`, or `REPAIR_ESTIMATE`, a `storage_uri`, and a `captured_at` recording when the document was created outside the system; every attachment starts with `verification_status` `PENDING`. A `ClaimsAdjuster` then works the queue: verifying requires the document still be `PENDING` (otherwise `ERR_DOCUMENT_INVALID_STATE`) and the claim still be in `DRAFT`, `SUBMITTED`, or `ACKNOWLEDGED` — a claim that has moved further along is locked against document churn and the attempt is `ERR_CLAIM_LOCKED` — while rejecting requires the document be `PENDING` and the request carry a non-empty `rejection_reason` (otherwise `ERR_REJECTION_REASON_REQUIRED`), with that reason persisted on the document only when it lands in `REJECTED`. Verification moves the document to `VERIFIED`; both terminal states, `VERIFIED` and `REJECTED`, increment the document's `version`.

### 3.3. Filing, Acknowledgment, and the Carmack Clock

Submitting a claim is the act that starts every statutory clock, and a `ClaimsClerk` may submit only a `DRAFT` claim (anything else is `ERR_CLAIM_INVALID_STATE`). Four conditions gate the transition. At least one attached document of kind `BOL` whose verification has not been rejected, and at least one of kind `COMMERCIAL_INVOICE` likewise un-rejected, must exist — a miss is `ERR_REQUIRED_DOCUMENT_MISSING`. The logical time at submission must be no later than the claim's `filing_deadline_at`, else `ERR_FILING_DEADLINE_PASSED`. And the claimed amount must still sit within the declared value, else `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE`.

A successful submission stamps `filing_received_at` with the current logical time, computes `filing_deadline_at` as the shipment's `ship_date` plus the carrier's `carmack_filing_days`, and computes `acknowledgment_due_at` as the filing receipt time plus the carrier's `carmack_acknowledgment_days`. It then ripples outward: the carrier's `claims_filed_count` increases by one and its `claim_ratio_bp` is recomputed; the lane's `claims_count` increases by one and `lane_claim_ratio_bp` is recomputed; the shipment moves from `DELIVERED` to `CLAIMED`; a `FILED` event is appended to the claim's log; and the claim's `version` increments. The claim's `filing_status` is now `SUBMITTED`.

Carrier acknowledgment is recorded by a `ClaimsAdjuster` and moves `SUBMITTED` to `ACKNOWLEDGED` (any other starting state is `ERR_CLAIM_INVALID_STATE`). The transition stamps `acknowledged_at`, appends an `ACKNOWLEDGED` event, and increments the claim's `version`. Lateness is judged by a strict comparison: an acknowledgment recorded later than `acknowledgment_due_at` sets `acknowledgment_late` to true and appends an `ACK_LATE_FLAGGED` event, while one landing exactly at the due instant is on time. The daily sweep of §2.7 applies the same strict rule to claims whose due instant passes with no acknowledgment recorded at all.

Withdrawal is the clerk's escape hatch, available from `DRAFT`, `SUBMITTED`, or `ACKNOWLEDGED` (any other state is `ERR_CLAIM_INVALID_STATE`) and landing in the terminal `WITHDRAWN`. Withdrawing a claim that had been submitted or acknowledged decrements the carrier's `claims_filed_count` and the lane's `claims_count` and recomputes both ratios; withdrawal from `DRAFT` touches no counters, since they were never incremented. In every case the shipment reverts from `CLAIMED` to `DELIVERED`, provided no other claim on the same shipment remains in a non-terminal state; the claim's `version` increments and a `WITHDRAWN` event is recorded. A shipment whose claims have all reached terminal states — paid, closed, withdrawn, or time-barred — closes out as `CLOSED`.

The clock is the last enforcer. A claim still `SUBMITTED` when the logical time passes `filing_deadline_at` becomes `TIME_BARRED`: the carrier's `claims_filed_count` is decremented and its ratio recomputed, a `TIME_BARRED` event is appended, and the version increments. A claim that reached `ACKNOWLEDGED` but never moved under review becomes `TIME_BARRED` once the logical time passes `filing_deadline_at` by more than 365 days — and here the counters deliberately do not move, because the claim was genuinely filed and remains part of the carrier's record; only the event and the version bump mark its passing.

### 3.4. Liability Assessment and the Limitation-of-Liability Pipeline

Once a claim is `ACKNOWLEDGED` and every attached document has reached `VERIFIED` — a single `PENDING` or `REJECTED` straggler blocks the step with `ERR_DOCUMENTS_NOT_VERIFIED` — a `ClaimsAdjuster` commissions a liability assessment. The request carries a `negligence_flag` of `NONE`, `CARRIER_NEGLIGENT`, `SHIPPER_FAULT`, `ACT_OF_GOD`, or `THIRD_PARTY`. The new assessment is computed immediately, arriving already in `SUBMITTED` state (its `DRAFT` state is traversed at creation), and its arrival drives the claim from `ACKNOWLEDGED` to `UNDER_REVIEW`; commissioning an assessment against a claim in any other state is `ERR_CLAIM_INVALID_STATE`. The assessment records the `assessed_by_user_id` of the acting adjuster and an immutable `liability_model_applied` snapshot of the carrier's model at that moment. If a prior assessment for the same claim still sits in `SUBMITTED`, it is moved to `SUPERSEDED` — the second terminal state of the assessment lifecycle alongside `APPROVED`.

The computation itself runs a pinned five-step pipeline over integer cents, rounding down at each multiplication step. Step one fixes the `limitation_basis_cents` as the lesser of the claim's `claimed_amount_cents` and the shipment's `declared_value_cents`. Step two applies the carrier's liability model to produce `carrier_limit_cents`: under `FULL_VALUE` the limit is the basis itself; under `RELEASED_RATE` it is the lesser of the basis and the product of the shipment's `total_weight_lbs` with the carrier's `released_rate_cents_per_lb`; under `PER_PACKAGE` it is the lesser of the basis and the product of `package_count` with `per_package_cap_cents`; under `PER_POUND` it is the lesser of the basis and the product of `total_weight_lbs` with `per_pound_cap_cents`. Step three applies the lane discount: the pipeline selects the carrier–lane assignment whose window covers the shipment's `ship_date` — `effective_from` inclusive, `effective_to` exclusive, ties broken in favor of the assignment with the earliest `created_at` — and if that assignment's `contracted_discount_pct` is above zero, the carrier limit is multiplied by one hundred minus the discount percentage and divided by one hundred, rounding down to a whole cent; the applied percentage is recorded as the assessment's `lane_discount_pct`. Step four applies negligence: `SHIPPER_FAULT` or `ACT_OF_GOD` collapses the carrier limit to zero; `CARRIER_NEGLIGENT` leaves the cap standing with no relaxation; `THIRD_PARTY` leaves it unchanged because recovery may be pursued separately through subrogation. Step five sets `computed_liability_cents` to the result, never less than zero. The order is load-bearing — basis, model cap, lane discount, negligence — and swapping the discount and cap steps yields different cents precisely because each multiplication rounds down on its own.

Completion of the pipeline writes back to the claim: `computed_liability_cents` is copied onto the claim, `liability_assessment_id` points at the new assessment, and `net_exposure_cents` is recomputed as the claim's computed liability minus its `salvage_credit_cents`, floored at zero. An `ASSESSED` event is appended and the claim's `version` increments.

A `ClaimsManager` may approve a `SUBMITTED` assessment — approving one in any other state is `ERR_ASSESSMENT_INVALID_STATE` — provided the manager is not the adjuster who performed it; a same-user approval is a segregation-of-duties violation, `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Approval moves the assessment to `APPROVED` and increments its `version`.

Before a claim is ever submitted, a lighter read-only preview serves adjusters, managers, and clerks alike. Against a `DRAFT` claim, the liability-preview capability runs the same pipeline minus the negligence step — no assessment exists yet, so the flag is ignored entirely — taking the basis from `claimed_amount_cents`, applying the model cap and lane discount, and returning a non-persisted estimate with `basis_cents`, `carrier_limit_cents`, `lane_discount_pct`, and `computed_liability_cents`. Nothing is stored; the preview exists so intake staff can sanity-check a claim's realistic ceiling before filing it.

### 3.5. Salvage, Reserves, and Net Exposure

A claim's `net_exposure_cents` is the thread that ties this section together: it is always the claim's `computed_liability_cents` minus its accumulated `salvage_credit_cents`, floored at zero, and it is recomputed on every assessment and on every salvage posting.

Damaged freight that can be recovered, repaired, or sold offsets what the carrier owes. A `SalvageCoordinator` schedules a disposition with a `disposition_kind` of `RETURN_TO_SHIPPER`, `AUCTION`, `DESTROY`, `DONATE`, or `REPAIR_AND_RETURN`; `gross_proceeds_cents` and `handling_cost_cents`, both of which must be zero or greater with violations reported under the fiscal family as `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE`; and a `scheduled_at` execution time that must lie in the future at scheduling — a past or present time trips the temporal family as `ERR_FILING_DEADLINE_PASSED` and the generic range family as `ERR_INVALID_TEMPORAL_RANGE`. A new disposition is `SCHEDULED`.

Execution — performed by a `SalvageCoordinator`, or by the system itself once the logical clock reaches `scheduled_at` — requires the disposition still be `SCHEDULED` (otherwise `ERR_SALVAGE_INVALID_STATE`), the logical time be at or past `scheduled_at` (otherwise `ERR_SALVAGE_NOT_YET_DUE`), and the claim be in `UNDER_REVIEW`, `OFFERED`, `DECLINED`, or `APPEALED` (otherwise `ERR_CLAIM_INVALID_STATE`). On execution the disposition's `net_credit_cents` is computed as its gross proceeds minus its handling cost, floored at zero; that credit is added to the claim's `salvage_credit_cents` — additively, and it may push the total credit past the computed liability, because the zero floor is applied separately on the exposure — and the claim's `net_exposure_cents` is recomputed. A `SALVAGE_POSTED` event is appended and the claim's `version` increments. A disposition that will not happen can instead be cancelled, moving `SCHEDULED` to `CANCELLED` and incrementing the disposition's `version`; both `EXECUTED` and `CANCELLED` are terminal.

Reserves are the finance function's answer to open exposure. A `FinanceController` posts a reserve with an `amount_cents` of zero or greater, but only while no other reserve on the same claim is still open — a second open reserve is refused with `ERR_RESERVE_ALREADY_OPEN`. Posting stamps `posted_at` from the logical clock, records the controller as `posted_by_user_id`, opens the reserve in `OPEN` state, sets the claim's `reserve_amount_cents` to the posted amount — the claim's reserve figure always equals the amount of its active `OPEN` reserve, and is zero whenever none exists — appends a `RESERVE_POSTED` event, and increments the claim's `version`. Releasing a reserve requires it still be `OPEN` (otherwise `ERR_RESERVE_INVALID_STATE`) and the claim be in one of the seven working states — `DRAFT`, `SUBMITTED`, `ACKNOWLEDGED`, `UNDER_REVIEW`, `OFFERED`, `DECLINED`, or `APPEALED` — since a terminal claim forbids the mutation with `ERR_CLAIM_ALREADY_TERMINAL`. Release moves the reserve to `RELEASED`, stamps `released_at`, zeroes the claim's `reserve_amount_cents`, appends a `RESERVE_RELEASED` event, and increments the claim's `version`.

How large should a reserve be? The system computes a sizing suggestion each time a reserve is posted, working multiplicatively from the claim's `net_exposure_cents`. The base is multiplied by 1.20 when the shipment's `commodity_class` is `HIGH_VALUE`; by 1.10 when the shipment's `is_concealed_damage` flag is set; by 1.15 when the carrier's `claim_ratio_bp` exceeds 1,500 basis points — the portfolio alert threshold; and by 1.05 when the lane's `lane_claim_ratio_bp` exceeds its own `baseline_claim_ratio_bp`. Because the multipliers compound multiplicatively rather than additively, their order of application does not change the product. The suggestion is then capped at twice the claim's `computed_liability_cents` and rounded half-up to a whole cent in a single final rounding step.

### 3.6. Settlement Negotiation and Payment

A claim carries two semi-independent state dimensions: `filing_status`, which tracks the workflow, and `payment_status`, which tracks remittance. They cross-gate at exactly one place — acceptance. A filing status of `PAID` is reached only with a payment status of `PAID_IN_FULL`; a partial payout is permitted only through the settlement path and lands the claim in `CLOSED_WITH_PAYMENT` with `PARTIAL` payment.

Negotiation opens when a `ClaimsAdjuster` extends a settlement offer against an `UNDER_REVIEW` claim. The claim must carry an assessment — its `liability_assessment_id` must be set, else `ERR_ASSESSMENT_REQUIRED` — and the request must carry `expected_claim_version` matching the claim's current `version` per §2.6, with a mismatch rejected as `ERR_STALE_VERSION`. The offered `amount_cents` must be greater than zero and no more than the claim's `net_exposure_cents`; an offer above the exposure is rejected under the fiscal family with `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE`. Each new offer bears a `round_number`, 1-indexed and unique per claim, incremented with every offer cycle, and records in `offered_by_role` which side proposed it — `ADJUSTER`, `MANAGER`, or `CARRIER`. Creating the offer computes its `authority_tier_required`: an amount no more than the carrier's `max_auto_settle_cents` requires `TIER_1` (adjuster-level) authority; otherwise an amount no more than 10,000,000 cents requires `TIER_2` (manager) authority; anything larger requires `TIER_3` (FinanceController) authority. Boundaries are inclusive at every rung — an offer of exactly `max_auto_settle_cents` stays `TIER_1`. The offer arrives in `OFFERED` state, the claim moves from `UNDER_REVIEW` to `OFFERED`, an `OFFER_EXTENDED` event is appended, and the claim's `version` increments.

Acceptance is where the tiers bite. A `ClaimsManager` or `FinanceController` accepts an offer only when the claim is `OFFERED` (otherwise `ERR_CLAIM_INVALID_STATE`), the settlement is `OFFERED` (otherwise `ERR_SETTLEMENT_INVALID_STATE`), the amount does not exceed the claim's current `net_exposure_cents` (otherwise `ERR_SETTLEMENT_EXCEEDS_NET_EXPOSURE`), the actor's authority is at least the offer's `authority_tier_required` — tiers are cumulative, so `TIER_3` satisfies `TIER_2` and `TIER_1` requirements — with a shortfall producing `ERR_AUTHORITY_TIER_INSUFFICIENT`, the actor is neither the user who extended the offer nor the adjuster who performed the assessment (a same-user overlap is `ERR_SEGREGATION_OF_DUTIES_VIOLATION`), and the claim's `reserve_amount_cents` covers the full amount (otherwise `ERR_RESERVE_INSUFFICIENT`). On acceptance the settlement becomes `ACCEPTED` with `approved_by_user_id` recording who accepted; the claim's `settlement_amount_cents` is fixed to the accepted amount; if the amount equals the net exposure the claim becomes `PAID` with `payment_status` `PAID_IN_FULL`, and if it falls short the claim becomes `CLOSED_WITH_PAYMENT` with `payment_status` `PARTIAL`; the active reserve is exhausted — moved to `EXHAUSTED` with `released_at` stamped and the claim's reserve figure zeroed; the carrier's `claims_paid_count` increases by one and `claim_ratio_bp` is recomputed; `OFFER_ACCEPTED` and `PAID_OUT` events are appended; and the claim's `version` increments.

Three other fates await an `OFFERED` settlement, each requiring the settlement still be `OFFERED` (otherwise `ERR_SETTLEMENT_INVALID_STATE`). A `ClaimsAdjuster` may counter it: the settlement becomes `COUNTERED`, the claim returns from `OFFERED` to `UNDER_REVIEW` where a fresh offer — the next `round_number` — may be extended, and the claim's `version` increments. A `ClaimsManager` may reject it: the settlement becomes `REJECTED`, an `OFFER_REJECTED` event is recorded, the claim moves to `DECLINED`, and the version increments. And the adjuster who created an offer may withdraw it — or a `ClaimsManager` may withdraw it in override — moving the settlement to `WITHDRAWN`, returning the claim to `UNDER_REVIEW`, and incrementing the version. Finally, per §2.7, an offer left standing more than 14 days past its creation expires on its own: the settlement becomes `EXPIRED` and the claim falls back to `UNDER_REVIEW` without any operator action. `ACCEPTED`, `REJECTED`, `WITHDRAWN`, and `EXPIRED` are terminal; `COUNTERED` feeds the next round.

### 3.7. Decline, Appeal, and Closure

Not every claim is paid. A `ClaimsAdjuster` may decline a claim that is `UNDER_REVIEW` (otherwise `ERR_CLAIM_INVALID_STATE`), provided an assessment exists (otherwise `ERR_ASSESSMENT_REQUIRED`) and the request carries `expected_claim_version` matching the claim's current `version` — a stale read, perhaps taken before a salvage credit reshaped the exposure, is rejected with `ERR_STALE_VERSION`. Declining appends a `DECLINED` event, increments the version, and moves the claim to `DECLINED`.

A declined claim is not yet dead. A `ClaimsAdjuster` may open an appeal — the claim must be `DECLINED`, its `appeal_round` must still be below 2 (a claim that has already consumed two rounds is refused with `ERR_APPEAL_ROUND_EXHAUSTED`), and the request must carry `expected_claim_version` per §2.6, because another writer may have advanced the round counter and changed eligibility since the client last read the claim. The appeal payload carries a free-text `justification` and a `requested_amount_cents` greater than zero. The new appeal opens in `OPEN` state with a `round_number` that is 1-indexed and unique within the claim, records its `opened_by_user_id`, increments the claim's `appeal_round`, moves the claim from `DECLINED` to `APPEALED`, appends an `APPEAL_OPENED` event, and increments the claim's `version`.

A `ClaimsManager` may escalate an `OPEN` appeal — but only while the claim is still `APPEALED`, otherwise `ERR_CLAIM_INVALID_STATE`, and only while the appeal is `OPEN`, otherwise `ERR_APPEAL_INVALID_STATE` — by naming an `escalated_to_user_id`, which moves the appeal to `UNDER_ESCALATION` and increments the appeal's `version`.

Decision is the manager's prerogative and requires the claim be `APPEALED` and the appeal be in `OPEN` or `UNDER_ESCALATION` (otherwise `ERR_APPEAL_INVALID_STATE`). The request carries a `decision` drawn from `PENDING`, `UPHOLD_DECLINE`, `OVERTURN`, and `PARTIAL`, with the appeal's `decision` field starting at `PENDING`. An `OVERTURN` decision demands that the deciding manager not be the user who opened the appeal — a same-user decide is `ERR_SEGREGATION_OF_DUTIES_VIOLATION` — and carries a `decided_amount_cents`; it replaces the claim's `computed_liability_cents` with the decided amount, superseding the prior assessment for settlement purposes, recomputes `net_exposure_cents` against the salvage credit with the zero floor, and returns the claim to `UNDER_REVIEW` for a fresh offer cycle. An `UPHOLD_DECLINE` decision returns the claim to `DECLINED`, where a further appeal round remains possible only if the round budget has not been exhausted. The `decided_amount_cents` is populated whenever the decision is `OVERTURN` or `PARTIAL` and remains null otherwise. Either way the appeal becomes `DECIDED`, an `APPEAL_DECIDED` event is appended, and both the appeal's and the claim's `version` increment; once the claim has left `APPEALED`, the system closes the appeal out as `CLOSED`, which is terminal alongside `DECIDED`.

Closure without payment is the final exit for a declined claim. A `ClaimsManager` may close a `DECLINED` claim only when its `appeal_round` has reached 2 or the request explicitly carries `waive_appeal` set to true — otherwise the closure is refused with `ERR_APPEAL_PENDING`, because the appellant still has rounds in reserve. Closing releases any open reserve on the claim: the reserve becomes `RELEASED` with `released_at` stamped, the claim's `reserve_amount_cents` is zeroed, a `RESERVE_RELEASED` event is appended, the claim's `version` increments, and the claim lands in the terminal `CLOSED_NO_PAYMENT`.

### 3.8. Subrogation and Third-Party Recovery

Once the shipper has been indemnified, the department turns to whoever was truly responsible. A `SubrogationSpecialist` opens a subrogation case only against a claim in `PAID` or `CLOSED_WITH_PAYMENT` — pursuing a third party before the shipper is made whole is refused with `ERR_CLAIM_NOT_PAID`. The case names a `responsible_party_kind` of `THIRD_PARTY_CARRIER`, `WAREHOUSE`, `BROKER`, `SHIPPER_VENDOR`, or `OTHER`, the `responsible_party_name`, and a `target_recovery_cents` greater than zero; it opens in `OPEN` state with `recovered_cents` and `recovery_ratio_bp` at zero.

The pursuit has its own small lifecycle. Sending a demand letter moves `OPEN` to `DEMAND_SENT`; the first departure from `OPEN` — wherever it leads — is what appends the `SUBROGATION_OPENED` event to the claim's log. Escalating to counsel moves `DEMAND_SENT` to `IN_LITIGATION`. Each of those steps increments the case's `version`.

Recovery can be agreed from any of the three active states — `OPEN`, `DEMAND_SENT`, or `IN_LITIGATION`. Settling takes a `recovered_cents` of zero or greater, stores it on the case, and recomputes `recovery_ratio_bp`: the recovered amount is multiplied by 10,000 and divided by the recovery target — a zero target treated as one — rounded half-up to whole basis points, and capped at 10,000 basis points so that over-recovery reports as 10,000. The recovery also reaches back to the claim: the recovered amount is subtracted from the claim's `net_exposure_cents`, floored at zero, a `SUBROGATION_RECOVERY` event is appended, and both the claim's and the case's `version` increment. The case lands in the terminal `SETTLED`. Where nothing more can be won, the specialist closes the case as `CLOSED_UNRECOVERABLE` — likewise terminal — from any of the same three active states, incrementing its `version`.

### 3.9. Claim-Ratio Analytics and Portfolio Aging

Two ratios run continuously beneath the workflow. Per carrier, `claims_filed_count` counts claims that ever entered `SUBMITTED` — established from the event stream, counting only the first `FILED` event per claim so that a resubmission after withdrawal never double-counts — while `claims_paid_count` counts claims currently in `PAID` or `CLOSED_WITH_PAYMENT`; `claim_ratio_bp` is the paid count multiplied by 10,000 and divided by the filed count, with a denominator of zero treated as one so that a carrier with no filings reports a ratio of zero, rounded half-up to whole basis points. Per lane, `shipments_count` counts shipments on the lane, `claims_count` counts claims on the lane that ever entered `SUBMITTED` under the same first-`FILED`-event rule, and `lane_claim_ratio_bp` follows the same multiply-divide-round shape with the same zero-denominator guard. Both ratios are recomputed on every claim transition into or out of the filed working set — `SUBMITTED`, `ACKNOWLEDGED`, `UNDER_REVIEW`, `OFFERED`, `DECLINED`, `APPEALED` — and into the paid states, and the carrier figure is additionally refreshed whenever a carrier is read. The carrier-ratio analytic accepts a `window` selector: `TRAILING_12M` restricts the input set to claims whose first `FILED` event falls within the trailing 365 days up to the current logical time, while `LIFETIME` — the default — applies no time filter. The lane-ratio analytic reports each lane's `lane_claim_ratio_bp` alongside its `baseline_claim_ratio_bp` so variance is visible at a glance.

Aging answers a different question: how old is the open book? Every claim in one of the six working statuses — `SUBMITTED`, `ACKNOWLEDGED`, `UNDER_REVIEW`, `OFFERED`, `DECLINED`, or `APPEALED` — is aged by taking the elapsed time between its `filing_received_at` and the current logical time and rounding down to whole days. A claim younger than 30 days falls in `B0_30`; from 30 up to but not including 60 days it falls in `B31_60`; from 60 up to but not including 90 days, `B61_90`; and 90 days or older, `B91_PLUS`. Boundaries land in the higher bucket — a claim exactly 30 days old is `B31_60`, not `B0_30`. Within each bucket, claims are ordered by `filing_received_at` ascending, ties broken by the claim's `created_at` ascending. The analytic response carries the four bucket counts.

## 4. Endpoint Definitions

All business endpoints are mounted under the `/freight-claims` prefix; the test-driving clock capability stands outside it. Operations that create a new resource — registering a carrier, opening a claim, attaching a document, commissioning an assessment, scheduling a salvage, opening an appeal, extending an offer, opening a subrogation case, posting a reserve, declaring a calendar row — return `201 Created`. Reads, and actions that modify an existing resource in place, return `200 OK`. Request and response bodies follow the envelope of §2.2; the narratives of §3 define each operation's parameters, preconditions, and effects.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | PlatformAdmin |
| POST | `/freight-claims/carriers` | Register a carrier | ClaimsManager |
| GET | `/freight-claims/carriers` | List carriers | Any |
| GET | `/freight-claims/carriers/{carrierId}` | Get a carrier | Any |
| POST | `/freight-claims/carriers/{carrierId}/suspend` | Suspend a carrier (no open exposure allowed) | ClaimsManager |
| POST | `/freight-claims/carriers/{carrierId}/reinstate` | Reinstate a suspended carrier | ClaimsManager |
| POST | `/freight-claims/carriers/{carrierId}/terminate` | Terminate a suspended carrier | FinanceController |
| POST | `/freight-claims/lanes` | Create a lane | ClaimsManager |
| GET | `/freight-claims/lanes` | List lanes | Any |
| GET | `/freight-claims/lanes/{laneId}` | Get a lane | Any |
| POST | `/freight-claims/lanes/{laneId}/retire` | Retire a lane | ClaimsManager |
| POST | `/freight-claims/carrier-lane-assignments` | Assign a carrier to a lane with discount and effective window | ClaimsManager |
| GET | `/freight-claims/carrier-lane-assignments` | List carrier–lane assignments | Any |
| GET | `/freight-claims/carrier-lane-assignments/{assignmentId}` | Get a carrier–lane assignment | Any |
| POST | `/freight-claims/shipments` | Register a delivered shipment | ClaimsClerk |
| GET | `/freight-claims/shipments` | List shipments | Any |
| GET | `/freight-claims/shipments/{shipmentId}` | Get a shipment | Any |
| POST | `/freight-claims/claims` | Open a new claim in DRAFT state against a shipment | ClaimsClerk |
| GET | `/freight-claims/claims` | List claims | Any |
| GET | `/freight-claims/claims/{id}` | Get a claim | Any |
| POST | `/freight-claims/claims/{id}/submit` | Submit a draft claim; stamps filing receipt and deadlines | ClaimsClerk |
| POST | `/freight-claims/claims/{id}/acknowledge` | Record carrier acknowledgment of a claim | ClaimsAdjuster |
| POST | `/freight-claims/claims/{id}/decline` | Decline a claim under review (optimistic concurrency) | ClaimsAdjuster |
| POST | `/freight-claims/claims/{id}/withdraw` | Withdraw a claim from DRAFT, SUBMITTED, or ACKNOWLEDGED | ClaimsClerk |
| POST | `/freight-claims/claims/{id}/close` | Close a declined claim with no payment | ClaimsManager |
| GET | `/freight-claims/claims/{id}/liability-preview` | Provisional limitation-of-liability computation (no persistence) | ClaimsClerk, ClaimsAdjuster, ClaimsManager |
| POST | `/freight-claims/claims/{id}/documents` | Attach a document to a claim | ClaimsClerk |
| GET | `/freight-claims/claims/{id}/documents` | List documents for a claim | Any |
| GET | `/freight-claims/claims/{id}/documents/{docId}` | Get a document | Any |
| POST | `/freight-claims/claims/{id}/documents/{docId}/verify` | Verify a document | ClaimsAdjuster |
| POST | `/freight-claims/claims/{id}/documents/{docId}/reject` | Reject a document | ClaimsAdjuster |
| POST | `/freight-claims/claims/{id}/assessments` | Create a liability assessment; supersedes a prior submitted one; drives the claim to UNDER_REVIEW | ClaimsAdjuster |
| GET | `/freight-claims/claims/{id}/assessments` | List assessments for a claim | Any |
| GET | `/freight-claims/claims/{id}/assessments/{assessmentId}` | Get an assessment | Any |
| POST | `/freight-claims/claims/{id}/assessments/{assessmentId}/approve` | Approve a submitted assessment | ClaimsManager |
| POST | `/freight-claims/claims/{id}/salvage` | Schedule a salvage disposition | SalvageCoordinator |
| GET | `/freight-claims/claims/{id}/salvage` | List salvage dispositions for a claim | Any |
| GET | `/freight-claims/claims/{id}/salvage/{salvageId}` | Get a salvage disposition | Any |
| POST | `/freight-claims/claims/{id}/salvage/{salvageId}/execute` | Execute a scheduled salvage disposition | SalvageCoordinator |
| POST | `/freight-claims/claims/{id}/salvage/{salvageId}/cancel` | Cancel a scheduled salvage disposition | SalvageCoordinator |
| POST | `/freight-claims/claims/{id}/appeals` | Open an appeal on a declined claim (optimistic concurrency) | ClaimsAdjuster |
| GET | `/freight-claims/claims/{id}/appeals` | List appeals for a claim | Any |
| GET | `/freight-claims/claims/{id}/appeals/{appealId}` | Get an appeal | Any |
| POST | `/freight-claims/claims/{id}/appeals/{appealId}/escalate` | Escalate an appeal to a manager | ClaimsManager |
| POST | `/freight-claims/claims/{id}/appeals/{appealId}/decide` | Decide an appeal | ClaimsManager |
| POST | `/freight-claims/claims/{id}/settlements` | Extend a settlement offer on a claim under review (optimistic concurrency) | ClaimsAdjuster |
| GET | `/freight-claims/claims/{id}/settlements` | List settlements for a claim | Any |
| GET | `/freight-claims/claims/{id}/settlements/{settlementId}` | Get a settlement | Any |
| POST | `/freight-claims/claims/{id}/settlements/{settlementId}/accept` | Accept a settlement; exhausts the reserve and pays out | ClaimsManager, FinanceController |
| POST | `/freight-claims/claims/{id}/settlements/{settlementId}/counter` | Counter an offer, returning the claim to UNDER_REVIEW | ClaimsAdjuster |
| POST | `/freight-claims/claims/{id}/settlements/{settlementId}/reject` | Reject an offer, declining the claim | ClaimsManager |
| POST | `/freight-claims/claims/{id}/settlements/{settlementId}/withdraw` | Withdraw an offer, returning the claim to UNDER_REVIEW | ClaimsAdjuster, ClaimsManager |
| POST | `/freight-claims/claims/{id}/subrogation` | Open a subrogation case on a paid claim | SubrogationSpecialist |
| GET | `/freight-claims/claims/{id}/subrogation` | List subrogation cases for a claim | Any |
| GET | `/freight-claims/claims/{id}/subrogation/{caseId}` | Get a subrogation case | Any |
| POST | `/freight-claims/claims/{id}/subrogation/{caseId}/send-demand` | Mark the demand letter sent | SubrogationSpecialist |
| POST | `/freight-claims/claims/{id}/subrogation/{caseId}/litigate` | Move the case to litigation | SubrogationSpecialist |
| POST | `/freight-claims/claims/{id}/subrogation/{caseId}/settle` | Settle the case; the recovered amount offsets claim net exposure | SubrogationSpecialist |
| POST | `/freight-claims/claims/{id}/subrogation/{caseId}/close-unrecoverable` | Close the case as unrecoverable | SubrogationSpecialist |
| POST | `/freight-claims/claims/{id}/reserves` | Post a reserve on a claim (only one open at a time) | FinanceController |
| GET | `/freight-claims/claims/{id}/reserves` | List reserves for a claim | Any |
| GET | `/freight-claims/claims/{id}/reserves/{reserveId}` | Get a reserve | Any |
| POST | `/freight-claims/claims/{id}/reserves/{reserveId}/release` | Release a reserve on a non-terminal claim | FinanceController |
| GET | `/freight-claims/claims/{id}/events` | Read the append-only event log for a claim | Any |
| POST | `/freight-claims/calendar` | Declare a calendar row (business day, weekend, or holiday) | PlatformAdmin |
| GET | `/freight-claims/calendar` | List calendar rows | Any |
| GET | `/freight-claims/analytics/carrier-claim-ratio` | Per-carrier claim ratio, windowed or lifetime | Any |
| GET | `/freight-claims/analytics/lane-claim-ratio` | Per-lane claim ratio and variance versus baseline | Any |
| GET | `/freight-claims/analytics/claim-aging` | Open claims bucketed by age | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_INVALID_TEMPORAL_RANGE` | 400 Bad Request |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_CARRIER_NOT_FOUND` | 404 Not Found |
| `ERR_LANE_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SALVAGE_NOT_FOUND` | 404 Not Found |
| `ERR_APPEAL_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SUBROGATION_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVE_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_LOCKED` | 409 Conflict |
| `ERR_DOCUMENT_INVALID_STATE` | 409 Conflict |
| `ERR_REJECTION_REASON_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ASSESSMENT_INVALID_STATE` | 409 Conflict |
| `ERR_ASSESSMENT_REQUIRED` | 409 Conflict |
| `ERR_SALVAGE_INVALID_STATE` | 409 Conflict |
| `ERR_SALVAGE_NOT_YET_DUE` | 409 Conflict |
| `ERR_APPEAL_INVALID_STATE` | 409 Conflict |
| `ERR_APPEAL_ROUND_EXHAUSTED` | 409 Conflict |
| `ERR_APPEAL_PENDING` | 409 Conflict |
| `ERR_SETTLEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_SETTLEMENT_EXCEEDS_NET_EXPOSURE` | 422 Unprocessable Entity |
| `ERR_AUTHORITY_TIER_INSUFFICIENT` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_RESERVE_INSUFFICIENT` | 402 Payment Required |
| `ERR_RESERVE_ALREADY_OPEN` | 409 Conflict |
| `ERR_RESERVE_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_CLAIM_NOT_PAID` | 409 Conflict |
| `ERR_OPEN_EXPOSURE_EXISTS` | 409 Conflict |
| `ERR_FILING_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_REQUIRED_DOCUMENT_MISSING` | 422 Unprocessable Entity |
| `ERR_DOCUMENTS_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE` | 422 Unprocessable Entity |
| `ERR_SHIPMENT_NOT_DELIVERED` | 409 Conflict |
