# Consumer Affairs & Product Quality Contact API — Product Requirements Document

## 1. Introduction

Consumer-packaged-goods companies learn about their own manufacturing defects from consumers before they learn about them from anyone else. A single phone call about a fragment of metal in a snack bar is all at once a customer-service event, a food-safety event, a regulatory-reporting obligation, an evidence-recovery problem and a statistical signal about one packaging line on one shift. Today those five readings of the same call live in five disconnected systems, which is why a company can pay goodwill on a complaint whose lot has already been withdrawn, or file an adverse-event report a day past its deadline because nobody noticed that the severity band shortened the clock.

This document specifies the Consumer Affairs & Product Quality Contact API: a single service that takes an inbound consumer touch on any channel, identifies the exact production lot from a batch code read off the pack, scores and bands the hazard, escalates illness and injury to regulatory affairs with a hard submission deadline, ships and tracks a sample-retrieval kit under chain-of-custody discipline, authorizes goodwill under segregation-of-duties controls, and continuously monitors complaint rates per million units produced so that a cluster on one lot, line or plant surfaces as a trend signal before it becomes a recall.

Two design commitments run through everything that follows. First, a complaint carries **two independent status dimensions** — a care-handling dimension and a regulatory dimension — that advance on their own schedules and are deliberately not allowed to block one another except at final closure. Second, **every quantitative rule has a provisional and an adjudicated form**: at intake the product may not even be identified, so the system scores what it can and re-scores once a supervisor has adjudicated the case. Implementers should expect the difference between the two forms to be visible in cents and in decimal places, not merely in narrative.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across every endpoint. Where §3 tells the business story, this section fixes the mechanics.

### 2.1. Actors, Headers and Role-Based Access Control

Every request to this API, with exactly one exception, must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal is acting. The single exception is the logical-clock endpoint `POST /_clock/set_current_utc`, which is a test-driving capability and does not require `X-User-ID`. A request that omits `X-User-ID`, or supplies it blank, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is inspected. If the header is present but does not resolve to an existing record — or resolves to a `StaffUser` whose `is_active` is false — the request is rejected with `ERR_UNKNOWN_ACTOR` (HTTP 401). Only after both of those checks pass does the server compare the declared role against the roles authorized for the endpoint in §4; a caller outside that list is rejected with `ERR_UNAUTHORIZED` (HTTP 403), and because that comparison happens before any path identifier is looked up, an unauthorized caller never learns whether the resource they named exists.

Six roles exist, spelled exactly as follows: `SystemAdmin`, `CareAgent`, `CareSupervisor`, `QualityLead`, `RegulatoryOfficer`, and `Consumer`.

Identity binding differs by role, and it matters:

- When `X-User-Role` is `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it in an audit context but never compares it to any entity's `id`. `SystemAdmin` is the reference-data steward and clock operator and holds no complaint-handling authority of any kind.
- When `X-User-Role` is `CareAgent`, `CareSupervisor`, `QualityLead`, or `RegulatoryOfficer`, `X-User-ID` is the `id` of the acting `StaffUser`. Every actor stamp the system writes — `intake_agent_ref` on a `Contact`, `created_by_ref` and `triaged_by_ref` on a `Complaint`, `authored_by_ref` and `decided_by_ref` on a `Remedy`, `determined_by_ref` and `submitted_by_ref` on a `RegulatoryReport`, `opened_by_ref` on a `TrendSignal` — is that same `StaffUser` identifier taken from the header. Those stamps are audit records, not navigable relationships; they are also the basis of every segregation-of-duties comparison, which compares the current `X-User-ID` against a previously written stamp on the same record.
- When `X-User-Role` is `Consumer`, `X-User-ID` is the `id` of the acting `Consumer` record. The self-service role may read its own consumer record and nothing else; an ownership check compares the requested consumer's `id` to `X-User-ID` and rejects a mismatch with `ERR_UNAUTHORIZED`.

A `StaffUser` is registered with a human-readable `staff_code` (1 to 32 characters, unique across all staff), a `full_name`, and exactly one `role` drawn from `CARE_AGENT`, `CARE_SUPERVISOR`, `QUALITY_LEAD`, or `REGULATORY_OFFICER`. Each staff member also carries an `authority_tier` — one of `TIER_1`, `TIER_2`, or `TIER_3`, defaulting to `TIER_1` when omitted — that caps the goodwill they may approve, and an `is_active` boolean that defaults to true. `SystemAdmin` itself is not a `StaffUser` role value; it is an operator capacity declared in the header.

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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of records returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. `offset` sets how many records to skip and defaults to 0; the smallest accepted value is 0 and there is no upper bound. A `limit` outside 1 through 100, a non-integer `limit` or `offset`, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400).

Unless a specific endpoint says otherwise, every list is ordered by `created_at` ascending. Where a deterministic tie-break is needed for internal processing, ordering is by `created_at` ascending as well — never by `id`. The only documented departure is a kit's custody chain, which is returned in `sequence_no` order.

List responses report `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. The Logical Clock

All time-dependent behaviour in this system — timestamp stamping, ageing, penalty decay, detection windows, kit return deadlines and regulatory submission deadlines — reads a server-held **logical clock** rather than wall-clock time. `SystemAdmin` sets it by supplying `current_utc`; the response echoes the newly effective `current_utc` alongside the `previous_utc` it replaced. Until the clock is set for the first time, it reads `2026-08-01T00:00:00Z`. Every subsequent evaluation of an age, a window boundary or a deadline uses whatever instant the clock currently holds.

### 2.5. Common Resource Properties and Audit Stamps

Every resource in this system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC instant with three fractional digits (for example `2026-08-01T00:00:00.000Z`).

Most resources — `StaffUser`, `Consumer`, `Plant`, `ProductionLine`, `Product`, `ProductionLot`, `Contact`, `Complaint`, `SampleKit`, `Remedy`, `RegulatoryReport`, `TrendSignal`, and `ResponseTemplate` — additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on every mutation, and `version`, an integer that increments by one on every mutation. Recomputing a derived field counts as a mutation: when a triage moves a lot's complaint buckets, when a fulfilment moves a consumer's goodwill totals, or when a signal transition re-derives a plant's posture, the affected record's `updated_at` is refreshed and its `version` is incremented even though the client never addressed that record directly.

Two record types are immutable append-only ledgers and are deliberately different. A `CustodyEvent` carries only `id` and `created_at`: it has no `updated_at` and no `version`, and no endpoint mutates or deletes one. A `SignalMembership` is likewise limited to `id` and `created_at`, with no `updated_at` and no `version`, and no update endpoint exists for it.

### 2.6. Numeric Precision and Monetary Discipline

Scores, rates and weights are decimal numbers carried to **2 decimal places**, rounded **half up**. This applies to `provisional_severity_score`, `adjudicated_severity_score`, `sentiment_index`, `weighted_complaint_count`, `observed_rate_ppm`, `threshold_ppm`, `severity_weight`, `transit_hours`, `uplift_pct`, and every rate reported by a computed read.

Two precision rules are unusually strict and must be honoured literally. First, the adjudicated severity score applies its two multipliers **sequentially, rounding half up to 2 decimal places after each multiplication** — never once at the end. A single fused multiplication produces a different cent in the general case, and the stepwise form is normative. Severity scores are not capped at 100. Second, **money is whole cents**: `requested_value_cents`, `base_value_cents`, `uplift_cents`, `payout_cents`, and every consumer- and lot-level goodwill total are integers, and each intermediate monetary value is rounded half up to zero decimal places the instant it is produced rather than at the end of the chain.

### 2.7. Revision Pinning on Complaint and Custody Writes

Two writes in this system are guarded by optimistic concurrency, because for both of them a blind retry silently destroys work rather than harmlessly repeating it.

Authoring a goodwill remedy requires the field `expected_complaint_version` in the request body. It is not optional. Its value must equal the parent `Complaint`'s current `version` — the value the author last observed when they read the complaint and priced the goodwill against its severity band, lot linkage and hold state. Every write that mutates a complaint (adjudicating severity at triage, sending a templated response, imposing or releasing a quality hold, marking or unmarking a duplicate) increments `Complaint.version`. If `expected_complaint_version` no longer matches, the create is rejected with `ERR_STALE_COMPLAINT_VERSION` (HTTP 412) and no `Remedy` record is written. The reason a version pin is required here rather than an idempotency key is that a second create on the same complaint legitimately supersedes the first live remedy, so a retry against a moved complaint would quietly discard the earlier draft.

Appending a chain-of-custody record requires the field `expected_sample_kit_version` in the request body, likewise non-optional, matching the parent `SampleKit`'s current `version`. Each successful append increments `SampleKit.version`. An append whose `expected_sample_kit_version` does not match is rejected with `ERR_STALE_SAMPLE_KIT_VERSION` (HTTP 412) and the chain is left untouched. A sequential append that first re-reads the kit and supplies the refreshed version legitimately succeeds; what is refused is an append written against a superseded view of the chain, because the appender's belief about the current sequence position is exactly what the ledger's integrity rests on.

No other endpoint takes a version field. Endpoints not named in this subsection perform no concurrency check.

### 2.8. Cascade and Reconciliation Across Consumers, Lots and Plants

A great deal of this system's state is derived, and derived state is reconciled inside the same request that triggers it — there is no deferred or eventual settlement.

**Consumer goodwill is a four-account ledger.** `goodwill_authorized_cents` accumulates the `payout_cents` of every remedy ever approved for that consumer. `goodwill_outstanding_cents` holds approved-but-unfulfilled goodwill, `goodwill_paid_cents` holds fulfilled goodwill, and `goodwill_voided_cents` holds goodwill reversed either after approval or after fulfilment. All four default to 0 and the invariant that must always hold is that paid plus outstanding plus voided equals authorized. `open_kit_count` counts that consumer's kits in `REQUESTED`, `SHIPPED`, `IN_TRANSIT_INBOUND`, or `RECEIVED`. `complaint_count` counts that consumer's complaints excluding those currently in `DUPLICATE`.

**Lot complaint counters are a partition.** `linked_complaint_count` is the total number of complaints ever linked to a lot, and it is split exhaustively across `provisional_complaint_count` (linked, not `DUPLICATE`, no adjudicated severity yet), `adjudicated_complaint_count` (linked, not `DUPLICATE`, carrying an adjudicated severity) and `duplicate_complaint_count` (linked and currently in `DUPLICATE`). The invariant is that `linked_complaint_count` always equals the sum of those three buckets; every operation that changes a complaint's adjudication or duplicate standing moves a unit from one bucket to another and leaves the total alone. The lot also carries `goodwill_charged_cents`, the sum of `payout_cents` for remedies fulfilled against complaints linked to that lot, decremented when such a remedy is voided after fulfilment.

**Plant posture is never set directly.** `oversight_posture` is re-derived from the plant's own population of trend signals after every signal transition and during every operations checkpoint, to a fixed point, in the same request. `open_investigation_count` is the number of that plant's signals in `INVESTIGATION_OPEN` or `RECALL_EVALUATION`; `recall_initiated_count` is the number in `RECALL_INITIATED`. The posture is `INVESTIGATION_HOLD` when at least one of the plant's signals is in `RECALL_EVALUATION` or `RECALL_INITIATED`; otherwise it is `WATCH` when `open_investigation_count` is at least 1; otherwise it is `NORMAL`. Read as a state machine, a plant moves `NORMAL → WATCH` when a signal for it enters `INVESTIGATION_OPEN` while no signal for that plant is in `RECALL_EVALUATION` or `RECALL_INITIATED`; it moves `WATCH → INVESTIGATION_HOLD` when any of its signals enters `RECALL_EVALUATION` or `RECALL_INITIATED`, and while it sits in `INVESTIGATION_HOLD` new production lots for that plant's lines are refused; it falls back `WATCH → NORMAL` once `open_investigation_count` reaches 0 with `recall_initiated_count` at 0; and it steps back `INVESTIGATION_HOLD → WATCH` when `recall_initiated_count` is 0 and at least one `INVESTIGATION_OPEN` signal remains.

### 2.9. Validation Precedence

The server evaluates rules in a single fixed order and returns the **first** failure it finds. The order is normative: when a request violates two rules, the caller sees the one that appears earlier in this ladder, and several placements below were chosen deliberately so that one failure masks another.

1. `X-User-ID` present on every request except `POST /_clock/set_current_utc` — otherwise `ERR_UNAUTHENTICATED` (401).
2. `X-User-ID` resolves to an existing `StaffUser` or `Consumer`, and where applicable that staff record has `is_active` true — otherwise `ERR_UNKNOWN_ACTOR` (401).
3. The actor's role appears in the endpoint's authorized-role list — otherwise `ERR_UNAUTHORIZED` (403). Evaluated before any path identifier is resolved.
4. Every `{id}` path parameter resolves to an existing row of the expected entity — otherwise a 404 specific to that entity: `ERR_CONSUMER_NOT_FOUND`, `ERR_PLANT_NOT_FOUND`, `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCTION_LOT_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_SAMPLE_KIT_NOT_FOUND`, `ERR_REMEDY_NOT_FOUND`, `ERR_REGULATORY_REPORT_NOT_FOUND`, `ERR_TREND_SIGNAL_NOT_FOUND`, `ERR_RESPONSE_TEMPLATE_NOT_FOUND`, or `ERR_STAFF_USER_NOT_FOUND`. Where a path nests identifiers, they are resolved strictly left to right and the first unresolvable one determines the error.
5. Every reference supplied in a request body resolves to an existing row of the referenced entity, checked after path-level existence, yielding the same family of 404 codes. This applies to `POST /production-lines`, `POST /production-lots`, `POST /contacts`, `POST /complaints`, `POST /sample-kits`, `POST /remedies`, `POST /regulatory-reports`, `POST /trend-signals`, `POST /complaints/{id}/respond`, and `POST /complaints/{id}/mark-duplicate`.
6. On `POST /complaints/{id}/mark-duplicate`, the referenced duplicate target exists and is not the complaint being marked — otherwise `ERR_DUPLICATE_TARGET_INVALID` (422).
7. All required body fields for the endpoint are present — otherwise `ERR_VALIDATION` (400). Applies to every POST and PATCH endpoint.
8. Every enum field carries one of its declared values and every numeric field falls inside its declared range — otherwise `ERR_VALIDATION` (400). Applies to every POST and PATCH endpoint.
9. `limit` is an integer from 1 through 100 and `offset` is an integer of at least 0 — otherwise `ERR_VALIDATION` (400). Applies to every list endpoint.
10. Fields the server owns — everything described in this document as computed or system-assigned — are never accepted from a client. If supplied they are silently ignored and never stored. This step produces no error and no rejection.
11. Unique codes are unique: `staff_code`, `external_ref`, `plant_code`, `sku`, `kit_code`, `template_code`, and `line_code` within its plant — otherwise `ERR_DUPLICATE_CODE` (409). Applies to `POST /staff-users`, `POST /consumers`, `POST /plants`, `POST /production-lines`, `POST /products`, `POST /sample-kits`, and `POST /response-templates`.
12. On `POST /remedies`, `expected_complaint_version` equals the parent complaint's current `version` — otherwise `ERR_STALE_COMPLAINT_VERSION` (412). Placed after existence and schema but **before every state rule**, so a stale read is reported even when the complaint has meanwhile moved into a state that would independently block the create.
13. On `POST /sample-kits/{id}/custody-events`, `expected_sample_kit_version` equals the parent kit's current `version` — otherwise `ERR_STALE_SAMPLE_KIT_VERSION` (412).
14. On `POST /complaints`, the source contact is `OPEN` or `LOGGED` — otherwise `ERR_CONTACT_CLOSED` (409).
15. On `POST /contacts/{id}/close-no-complaint`, the contact's `complaint_count` is 0 — otherwise `ERR_CONTACT_HAS_COMPLAINTS` (409).
16. The complaint's `handling_status` permits the requested handling transition — otherwise `ERR_COMPLAINT_STATE_INVALID` (409), including any attempt to move out of terminal `CLOSED`. Applies to `POST /complaints/{id}/triage`, `/respond`, `/resolve`, `/close`, `/quality-hold`, `/release-hold`, `/mark-duplicate`, `/unmark-duplicate`, and `/identify-product`.
17. The complaint's `regulatory_status` permits the requested regulatory transition, independently of `handling_status` — otherwise `ERR_REGULATORY_STATE_INVALID` (409). Applies to `POST /regulatory-reports` and to `POST /regulatory-reports/{id}/determine`, `/submit`, and `/withdraw`; the same code guards `POST /complaints/{id}/close` when the regulatory dimension is unsettled. A `POST /regulatory-reports` against a complaint that already has a non-withdrawn report is rejected with `ERR_REPORT_ALREADY_OPEN` (409).
18. The remedy's `status` permits the requested transition — otherwise `ERR_REMEDY_STATE_INVALID` (409). Applies to `POST /remedies/{id}/submit`, `/decide`, `/fulfill`, and `/void`. Deliberately ranked **above** the authority-tier fiscal rule, so a remedy that is both in the wrong state and beyond the decider's tier reports the state error.
19. The kit's `status` permits the requested transition or custody append — otherwise `ERR_SAMPLE_KIT_STATE_INVALID` (409), including lockdown of the terminal `LAB_ACCEPTED`, `EXPIRED`, and `CANCELLED` states. Applies to `POST /sample-kits/{id}/ship`, `/receive`, `/lab-accept`, `/cancel`, and `POST /sample-kits/{id}/custody-events`.
20. The signal's `status` permits the requested transition — otherwise `ERR_TREND_SIGNAL_STATE_INVALID` (409). Applies to `POST /trend-signals/{id}/open-investigation`, `/dismiss`, `/escalate-recall-evaluation`, `/initiate-recall`, and `/close-no-action`.
21. The lot's `release_status` permits the requested transition — otherwise `ERR_LOT_STATE_INVALID` (409), including lockdown of terminal `WITHDRAWN`. Applies to `POST /production-lots/{id}/hold`, `/release`, and `/withdraw`.
22. The template's `status` permits the requested transition — otherwise `ERR_TEMPLATE_STATE_INVALID` (409). Applies to `POST /response-templates/{id}/activate` and `/retire`; the same code is returned when a non-`ACTIVE` template is selected on `POST /complaints/{id}/respond`.
23. The report is `OPEN` when a determination is recorded and `DETERMINED_REPORTABLE` when it is submitted, and is not already terminal when it is withdrawn — otherwise `ERR_REPORT_STATE_INVALID` (409). Applies to `POST /regulatory-reports/{id}/determine`, `/submit`, and `/withdraw`. This guard is separate from the complaint's regulatory dimension in step 17.
24. On `POST /complaints/{id}/triage`, the complaint's `product_identification_status` is `RESOLVED` — otherwise `ERR_PRODUCT_UNIDENTIFIED` (409).
25. On `POST /regulatory-reports/{id}/determine`, a `NOT_REPORTABLE` determination is refused when the complaint's `effective_severity_band` is `S1` — `ERR_S1_MUST_BE_REPORTABLE` (422).
26. On `POST /complaints/{id}/respond`, the complaint's linked lot is not `WITHDRAWN` — otherwise `ERR_LOT_WITHDRAWN` (409). Ranked **above** the template-eligibility rules in steps 42 and 43, so a withdrawn lot masks a template mismatch.
27. On `POST /complaints/{id}/release-hold`, no trend signal containing this complaint is in `RECALL_EVALUATION` — otherwise `ERR_RECALL_EVALUATION_ACTIVE` (409).
28. On `POST /production-lots/{id}/release`, no trend signal covering this lot is in `INVESTIGATION_OPEN` or `RECALL_EVALUATION` — otherwise `ERR_SIGNAL_INVESTIGATION_ACTIVE` (409).
29. On `POST /trend-signals/{id}/initiate-recall`, every member complaint whose `regulatory_status` is `REPORTABLE` has a report in `SUBMITTED` — otherwise `ERR_REGULATORY_SUBMISSION_PENDING` (409).
30. On `POST /trend-signals/{id}/escalate-recall-evaluation`, at least one member complaint has `effective_severity_band` of `S1` or `S2` — otherwise `ERR_SEVERITY_TOO_LOW_FOR_RECALL` (422).
31. On `POST /remedies/{id}/decide`, the complaint's kit, if one exists, is not in `REQUESTED`, `SHIPPED`, or `IN_TRANSIT_INBOUND` — otherwise `ERR_SAMPLE_KIT_IN_FLIGHT` (409).
32. On `POST /production-lots`, the owning plant's `oversight_posture` is not `INVESTIGATION_HOLD` — otherwise `ERR_PLANT_UNDER_INVESTIGATION_HOLD` (409). The blocking state lives two entities away: the posture is itself derived from the plant's trend-signal population.
33. On `POST /contacts`, `received_at` is not after the logical clock — otherwise `ERR_RECEIVED_AT_IN_FUTURE` (422).
34. On `POST /sample-kits/{id}/ship`, the consumer holds no other kit whose closed occupancy interval contains the prospective `shipped_at` — otherwise `ERR_KIT_INTERVAL_CONFLICT` (409). Ranked **above** the address-completeness rule in step 38, so an interval collision masks a missing postal code.
35. On `POST /sample-kits/{id}/custody-events`, the appended `occurred_at` is not earlier than the previous event's `occurred_at` — otherwise `ERR_CUSTODY_OUT_OF_ORDER` (422).
36. On `POST /trend-signals`, the requested window does not strictly overlap an existing `DETECTED`, `INVESTIGATION_OPEN`, or `RECALL_EVALUATION` signal for the same scope key — otherwise `ERR_SIGNAL_WINDOW_OVERLAP` (409). Two windows overlap when the first starts before the second ends and the second starts before the first ends; windows that merely touch at a boundary therefore coexist, so a window running from 1 July up to 1 August and one running from 1 August up to 15 August are both permitted.
37. On `POST /trend-signals`, `window_end` is strictly after `window_start` — otherwise `ERR_WINDOW_INVALID` (422).
38. On `POST /sample-kits/{id}/ship`, the consumer's `postal_code` is present — otherwise `ERR_CONSUMER_ADDRESS_MISSING` (422).
39. On `POST /sample-kits/{id}/custody-events`, the appended `event_type` is the one the required custody sequence expects at the next position — otherwise `ERR_CUSTODY_SEQUENCE_INVALID` (422). Steps cannot be skipped, reordered, or repeated.
40. On `POST /remedies/{id}/decide` with a revision decision, `revision_count` is still below the revision cap — otherwise `ERR_REVISION_LIMIT_REACHED` (409).
41. On `POST /trend-signals`, `scope_level`, `production_line_id`, and `lot_id` are mutually consistent — a `LOT`-scope signal supplies both the line and the lot, a `LINE`-scope signal supplies the line and leaves the lot empty, and a `PLANT`-scope signal leaves both empty. A violation is `ERR_SCOPE_SHAPE_INVALID` (422).
42. On `POST /complaints/{id}/respond`, the chosen template is `ACTIVE` and its `applies_to_type` is either the complaint's `complaint_type` or `ANY` — otherwise `ERR_TEMPLATE_TYPE_MISMATCH` (422).
43. On `POST /complaints/{id}/respond`, the template's `max_band_allowed` is no less severe than the complaint's `effective_severity_band` — otherwise `ERR_TEMPLATE_BAND_TOO_LOW` (422).
44. On `POST /complaints/{id}/mark-duplicate`, the duplicate target belongs to the same consumer and is not itself in `DUPLICATE` — otherwise `ERR_DUPLICATE_TARGET_INVALID` (422). Duplicate chains are one level deep and never cross consumers.
45. On `POST /remedies/{id}/decide`, the deciding staff member's `authority_tier` rank is at least the remedy's `authority_tier_required` rank, the decider differs from the author, and the computed payout does not exceed the goodwill ceiling. A tier shortfall is `ERR_AUTHORITY_TIER_INSUFFICIENT` (403); a decider identical to the author is `ERR_SEGREGATION_OF_DUTIES` (409); a payout above the ceiling is `ERR_GOODWILL_ABOVE_MAX` (422), and that ceiling check also runs when the remedy is first authored and when it is submitted. This family is ranked **last**, so every state and safety rule above masks it.

`ERR_SIGNAL_EMPTY_MEMBERSHIP` (422) sits alongside the signal rules: it is returned when an investigation is opened on a signal whose `membership_count` is 0, and when a manually raised window turns out to contain no eligible complaint at all.

### 2.10. The Two Status Dimensions of a Complaint

A `Complaint` carries two enumerated status fields that advance independently. `handling_status` is the care-workflow dimension and takes one of `INTAKE`, `TRIAGED`, `AWAITING_SAMPLE`, `IN_RESOLUTION`, `ON_QUALITY_HOLD`, `RESOLVED`, `CLOSED`, or `DUPLICATE`; it begins at `INTAKE` and `CLOSED` is terminal. `regulatory_status` is the regulatory dimension and takes one of `NOT_APPLICABLE`, `ESCALATED`, `REPORTABLE`, `NOT_REPORTABLE`, or `SUBMITTED`; it begins at `NOT_APPLICABLE` and `SUBMITTED` is terminal for that dimension. The regulatory dimension advances only through the lifecycle of a regulatory report and never blocks, or is blocked by, the handling dimension — with exactly one exception, which is that final closure requires the regulatory dimension to have settled.

### 2.11. Path Resolution for Nested Reads

Several read paths nest one identifier under another — a plant's production lines, a kit's custody events, a signal's memberships, a complaint's signal memberships. In every such case the identifiers are validated left to right, and the request fails on the **first** identifier in the path that does not resolve. A request for the custody events of a non-existent kit therefore returns `ERR_SAMPLE_KIT_NOT_FOUND` and never attempts to enumerate events. The same precedence applies to writes: a parent's existence is established before any child-level rule is evaluated.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Plants, Lines, Products and Production Lots

Before a single complaint can be categorized, the manufacturing world it refers to has to exist in the system. A `SystemAdmin` registers each manufacturing `Plant` with a unique `plant_code`, a `name`, and a `region` drawn from `MW`, `NE`, `SE`, or `WEST`. Each plant then receives one or more production lines, created with the owning plant identifier as `plant_id`, a `line_code` that must be unique within that plant, and a `nominal_units_per_hour` rated throughput of at least 1. The line's `plant_id` is fixed at creation and never changes afterwards. A line maintains a `lot_count` of the production lots recorded against it, and the plant is the line's parent for retrieval purposes.

Finished goods are registered as products, each with a unique `sku`, a `name`, a merchandising `category` of `SNACK`, `BEVERAGE`, `DAIRY`, or `NON_FOOD`, a `unit_retail_price_cents` of at least 1, a `units_per_case` of at least 1, and — most consequentially — an `is_regulated_food` boolean. That single flag has two downstream effects: it brings the regulated multiplier into adjudicated severity scoring, and it causes illness complaints against the product to be escalated to regulatory affairs automatically.

A **production lot** is one production run and the denominator for all rate monitoring. It is registered by a `SystemAdmin` or a `QualityLead` with the `product_id` and `production_line_id` it belongs to — both immutable once set — a `batch_code` transcribed exactly as printed on pack, a `code_date` at UTC midnight, and a `units_produced` count of zero or more consumer units. On creation the server derives `normalized_batch_code` by upper-casing the `batch_code` and removing every character that is not a letter A through Z or a digit 0 through 9; that normalized form, not the raw one, is what consumer-reported codes are matched against, and lots may be filtered by it. Registering a lot also increments the owning line's `lot_count`. A lot whose owning plant currently sits in `INVESTIGATION_HOLD` cannot be registered at all: the attempt fails with `ERR_PLANT_UNDER_INVESTIGATION_HOLD`.

A lot's quality disposition is tracked in `release_status`, which begins at `RELEASED`. A `QualityLead` may place a released lot on hold, moving it `RELEASED → HOLD`, optionally recording a `reason`. A held lot returns `HOLD → RELEASED` only when no trend signal covering it sits in `INVESTIGATION_OPEN` or `RECALL_EVALUATION`; while one does, the attempt is refused with `ERR_SIGNAL_INVESTIGATION_ACTIVE`. From `HOLD` a lot may instead be withdrawn permanently, `HOLD → WITHDRAWN`, which is terminal and which freezes all canned consumer messaging that references the lot from that point forward. A lot cannot be withdrawn directly from `RELEASED`, and nothing moves out of `WITHDRAWN`; either attempt yields `ERR_LOT_STATE_INVALID`. Reading a lot returns its complaint-count buckets and its `goodwill_charged_cents` ledger.

### 3.2. Contact Intake, Complaint Registration and Batch-Code Resolution

Consumers reach the company on four channels, and each inbound touch is logged as a `Contact` by a `CareAgent` or `CareSupervisor`. The record names the `consumer_id` it belongs to (fixed once written), a `channel` of `PHONE`, `EMAIL`, `SOCIAL`, or `WEB`, a `received_at` instant, the verbatim `raw_message` of between 1 and 4,000 characters holding the consumer's own words or the call summary, and optionally the `handle_or_address` the contact arrived from. A contact logged with a `received_at` later than the current logical clock is refused with `ERR_RECEIVED_AT_IN_FUTURE`. Each contact starts with `status` `OPEN`, a `complaint_count` of 0, and an `intake_agent_ref` stamped from the acting staff identifier.

A consumer record itself is created with a unique `external_ref` from the CRM and a `full_name`, plus optional `email`, `phone`, `postal_code`, and an `is_vulnerable_flag` that defaults to false and marks membership in a vulnerable cohort such as minors, the elderly, or the immunocompromised. All four optional fields default to empty, and all four remain editable afterwards — the `postal_code` in particular is frequently supplied later, since it is needed only when a sample kit ships. A newly created consumer's `sentiment_index` starts at the neutral baseline of 50.

Not every contact produces a complaint. A `CareAgent` or `CareSupervisor` may close an `OPEN` contact as having produced none, moving it `OPEN → CLOSED_NO_COMPLAINT` with an optional `reason`; that state is terminal. Closing this way is only legitimate while `complaint_count` is still 0, and a contact that already carries a complaint is refused with `ERR_CONTACT_HAS_COMPLAINTS`. Conversely, once a contact has been closed as no-complaint it can never spawn one, and the attempt fails with `ERR_CONTACT_CLOSED`.

When the contact does describe a problem, a complaint is registered against it. The payload carries the `contact_id`, a `complaint_type` of `FOREIGN_MATERIAL`, `ILLNESS`, `PACKAGING`, or `QUALITY`, and a set of optional hazard descriptors: the `reported_batch_code` the consumer read off the pack, the `pack_code_date` printed alongside it, a `foreign_object_class` of `NONE`, `SOFT`, `HARD_BLUNT`, or `HARD_SHARP` (defaulting to `NONE`), the booleans `medical_attention_sought` and `hospitalization` (both defaulting to false), a `vulnerable_consumer` boolean asserted at intake for this particular case (defaulting to false, and distinct from the consumer's standing cohort flag), a `symptom_codes` array of up to 12 strings of 1 to 16 characters each (defaulting to empty), and a `units_claimed` count between 1 and 100 (defaulting to 1) that later caps refund and replacement goodwill. The complaint's `consumer_id` is copied from the parent contact rather than supplied, and `created_by_ref` is stamped from the acting staff identifier. Registering the complaint moves the contact `OPEN → LOGGED`, or leaves an already-`LOGGED` contact in `LOGGED` when a second complaint is registered from the same touch; either way the contact's `complaint_count` and the consumer's `complaint_count` each rise by one.

**Batch-code resolution** runs immediately. The reported code is normalized the same way lot codes are — upper-cased with every character that is not a letter A through Z or a digit 0 through 9 removed — and compared for exact equality against every lot's `normalized_batch_code`. No prefix matching and no fuzzy matching is performed. If no `reported_batch_code` was supplied, or the normalized form matches no lot, `product_identification_status` stays `UNRESOLVED`, `lot_id` stays empty, and `product_id` is left as it was. If exactly one lot matches, `product_identification_status` becomes `RESOLVED` and both `lot_id` and `product_id` are taken from that lot. If more than one lot matches, the `pack_code_date` becomes the tie-breaker: the candidates are narrowed to those whose `code_date` equals the supplied `pack_code_date`, and only if that narrowing leaves exactly one lot does resolution succeed from it. When `pack_code_date` was not supplied, or when narrowing still leaves more than one or none, the request is refused with `ERR_BATCH_CODE_AMBIGUOUS`. A successful resolution also raises the lot's `linked_complaint_count` and its `provisional_complaint_count` by one each.

Consumers misread codes, so a `CareAgent` or `CareSupervisor` may re-run resolution later by supplying a corrected `reported_batch_code` and an optional `pack_code_date`. Re-resolution obeys exactly the same matching and ambiguity rules, and when it lands on a different lot the bucket counters on both the old and the new lot are moved accordingly. What re-resolution deliberately does **not** do is recompute the provisional severity: that figure never depended on which product was involved.

**Provisional severity** is computed at registration, from the complaint's own descriptors alone. The number of scoring symptoms is the count of entries in `symptom_codes`, or 4 if there are more than 4 — only the first four reported symptoms score. The additive hazard total is then the sum of four contributions: a type component worth 40 points for `FOREIGN_MATERIAL`, 50 for `ILLNESS`, 20 for `PACKAGING`, and 10 for `QUALITY`; an object component worth 0 points for `NONE`, 5 for `SOFT`, 15 for `HARD_BLUNT`, and 30 for `HARD_SHARP`; 25 points when `medical_attention_sought` is true and nothing when it is false, plus 35 points when `hospitalization` is true and nothing when it is false; and 3.5 points for each scoring symptom. That additive total, rounded half up to 2 decimal places, is the `provisional_severity_score`. Its `provisional_severity_band` is `S1` when the score is at least 90, otherwise `S2` when it is at least 60, otherwise `S3` when it is at least 30, and otherwise `S4`. At intake — and until adjudication happens — `effective_severity_band` equals `provisional_severity_band`. Neither the regulated-food multiplier nor the vulnerability multiplier is applied at this stage, because at intake the product may not be identified at all and neither weighting could be justified.

### 3.3. Severity Adjudication at Triage and Its Fan-Out

Triage is where a supervisor's judgement replaces the intake estimate, and it is the single busiest fan-out point in the system. Either a `CareSupervisor` or a `QualityLead` may adjudicate, optionally recording a `reviewer_note`. The complaint must be in `INTAKE`, and its `product_identification_status` must be `RESOLVED`; an unidentified complaint cannot be adjudicated at all, because both the regulated multiplier and the rate denominator would be unknown, and the attempt is refused with `ERR_PRODUCT_UNIDENTIFIED`.

Adjudication recomputes the score from the same additive hazard total described above, then applies two multipliers **one after the other, rounding half up to 2 decimal places after each one**. The vulnerability condition is satisfied when the complaint's own `vulnerable_consumer` flag is true or the consumer's standing `is_vulnerable_flag` is true; when it holds, the additive total is multiplied by 1.15 and the product is rounded half up to 2 decimal places, and when it does not hold the additive total simply carries forward unchanged. That first result is then multiplied by 1.075 when the resolved lot's product has `is_regulated_food` true, and rounded half up to 2 decimal places again; when the product is not a regulated food, the first result carries forward unchanged. The value that survives both steps is the `adjudicated_severity_score`, and its `adjudicated_severity_band` is banded with the same thresholds as the provisional band: at least 90 is `S1`, at least 60 is `S2`, at least 30 is `S3`, and anything lower is `S4`. Scores are not capped at 100. Fusing the two multipliers into one multiplication is not an acceptable shortcut — the stepwise rounding order is normative and produces a different cent in the general case.

Once an adjudicated score exists, `effective_severity_band` switches to `adjudicated_severity_band` and stays there; before adjudication it reads `provisional_severity_band`. The transition itself moves the complaint `INTAKE → TRIAGED` and stamps `triaged_by_ref` with the adjudicating staff identifier.

Four consequences then fan out from a single triage:

- The linked lot's counters shift one unit from `provisional_complaint_count` into `adjudicated_complaint_count`, leaving `linked_complaint_count` unchanged.
- When the adjudicated band is `S1` or `S2` **and** the `complaint_type` is `ILLNESS` or `FOREIGN_MATERIAL`, a regulatory report is created automatically in `OPEN` with its `escalated_at` set to the logical clock and its `due_at` derived from the band, and the complaint's `regulatory_status` advances `NOT_APPLICABLE → ESCALATED`.
- When the adjudicated band is `S1`, the linked lot is additionally moved `RELEASED → HOLD`.
- The owning plant's `oversight_posture` is re-derived afterwards.

### 3.4. Duplicate Handling and Counter Reconciliation

Consumers who call twice, or who call and then also post on social, generate the same complaint twice. Only a `CareSupervisor` may reconcile that. Marking a complaint a duplicate requires supplying the `duplicate_of_complaint_id` of the surviving complaint, and the target must exist, must be a different complaint from the one being marked, must not itself be in `DUPLICATE`, and must belong to the same consumer. A target that is the complaint itself, or that does not exist, or that is itself a duplicate, or that belongs to another consumer, is refused with `ERR_DUPLICATE_TARGET_INVALID` — duplicate chains are exactly one level deep and never cross consumers.

Marking is permitted from `INTAKE` or from `TRIAGED`, and in both cases the complaint moves to `DUPLICATE` with `duplicate_of_complaint_id` recorded. The lot counters shift one unit into `duplicate_complaint_count` from whichever bucket the complaint currently occupies — out of `provisional_complaint_count` for an `INTAKE` complaint and out of `adjudicated_complaint_count` for a `TRIAGED` one — leaving `linked_complaint_count` untouched. The consumer's `complaint_count` drops by one, because duplicates are excluded from that figure.

Restoring a wrongly marked duplicate reverses all of it, optionally recording a `reason`. The complaint must currently be in `DUPLICATE`, and where it lands depends on whether adjudication had already happened: with no `adjudicated_severity_score` on file it goes `DUPLICATE → INTAKE` and the lot counter unit moves out of `duplicate_complaint_count` back into `provisional_complaint_count`; with an `adjudicated_severity_score` present it goes `DUPLICATE → TRIAGED` and the unit moves back into `adjudicated_complaint_count` instead. Either way `duplicate_of_complaint_id` is cleared and the consumer's `complaint_count` rises by one.

### 3.5. Sample Retrieval Kits and the Chain of Custody

Recovering the physical product is what turns a consumer anecdote into laboratory evidence, and the kit that recovers it is tracked under formal chain-of-custody discipline. A `CareAgent` or `CareSupervisor` requests a kit for a `TRIAGED` complaint by supplying the `complaint_id`, a `kit_code` unique across all kits and printed on the mailing label, and the `seal_id_issued` of the tamper seal packed inside. The kit's `consumer_id` is copied from the complaint, its `status` starts at `REQUESTED`, its `chain_integrity_status` starts at `PENDING`, its `disposition` starts at `PENDING`, and its `custody_event_count` starts at 0. Requesting the kit moves the complaint `TRIAGED → AWAITING_SAMPLE` and raises the consumer's `open_kit_count` by one.

Dispatching the kit, optionally with a `carrier_note`, moves it `REQUESTED → SHIPPED` and stamps four instants at once. `shipped_at` is the logical clock. `expected_return_by` is 14 days after `shipped_at`. `occupied_from` is 48 hours before `shipped_at`, and `occupied_until` is 48 hours after `expected_return_by`; together they bound a **closed** exclusivity interval — closed at both ends, unlike the half-open detection window used for trend monitoring — during which the consumer may not hold another kit. Dispatch is refused with `ERR_KIT_INTERVAL_CONFLICT` when any other kit belonging to the same consumer, in `REQUESTED`, `SHIPPED`, `IN_TRANSIT_INBOUND`, or `RECEIVED`, has an occupancy interval that contains the prospective `shipped_at`; because the interval is closed, a prospective `shipped_at` exactly equal to another kit's `occupied_until` still collides. Dispatch is also refused with `ERR_CONSUMER_ADDRESS_MISSING` when the consumer has no `postal_code` on file, though an interval collision is reported first. Finally, dispatch automatically appends the chain's first custody record, a `KIT_ISSUED` event at `sequence_no` 1.

Custody records are appended, never edited. Each append is a request from a `CareAgent`, `CareSupervisor`, or `QualityLead` carrying an `event_type`, the `occurred_at` physical time of the step, a free-text `actor_label` naming the physical custodian, the `expected_sample_kit_version` described in §2.7, and optionally the `seal_id_observed` read at that step and any `notes`. The server assigns `sequence_no` as the 1-based position in the kit's chain, records the append against `sample_kit_id`, raises the kit's `custody_event_count`, and increments the kit's `version`. The chain must follow exactly five steps in exactly this order: `KIT_ISSUED`, `CONSUMER_SEALED`, `CARRIER_PICKUP`, `LAB_RECEIVED`, `LAB_OPENED`. An `event_type` that is not the one expected at the next position is refused with `ERR_CUSTODY_SEQUENCE_INVALID`, and an `occurred_at` earlier than the previous event's `occurred_at` is refused with `ERR_CUSTODY_OUT_OF_ORDER`. Appending the `CARRIER_PICKUP` event moves the kit `SHIPPED → IN_TRANSIT_INBOUND`, and that transition additionally requires that the immediately preceding custody event was `CONSUMER_SEALED`.

The **chain integrity projection** re-runs over the whole ordered chain after every append, and again when the kit is received and accepted. `transit_hours` is the number of hours between the `CARRIER_PICKUP` event's `occurred_at` and the `LAB_RECEIVED` event's `occurred_at`, rounded half up to 2 decimal places. The chain is `INTACT` only when all six of the following hold: every appended position carries the event type the required sequence expects there; all five required events are present; `occurred_at` is non-decreasing across the ordered chain; the `CONSUMER_SEALED` event's `seal_id_observed` equals the kit's `seal_id_issued`; the `LAB_RECEIVED` event's `seal_id_observed` also equals `seal_id_issued`; and `transit_hours` is at most 240 — a transit of exactly 240.00 hours is still `INTACT`. If any of those six fails, `chain_integrity_status` is `BROKEN`. While fewer than five events exist and none of the six conditions has already been violated, the status remains `PENDING`.

A `QualityLead` logs the inbound kit once a `LAB_RECEIVED` event has been appended, moving it `IN_TRANSIT_INBOUND → RECEIVED`; that sets `received_at`, computes `transit_hours`, copies `seal_id_returned` from the `LAB_RECEIVED` event's observed seal, and re-runs the integrity projection. Accepting the kit into the lab, optionally with a `lab_note`, moves it `RECEIVED → LAB_ACCEPTED` and requires that `custody_event_count` has reached exactly 5. Acceptance sets `disposition` to `USABLE` when `chain_integrity_status` is `INTACT` and forces it to `UNUSABLE` otherwise, moves the parent complaint `AWAITING_SAMPLE → IN_RESOLUTION`, and lowers the consumer's `open_kit_count` by one.

Two paths end a kit's life without evidence. A `CareSupervisor` may cancel an unreturned kit, optionally with a `reason`, from either `REQUESTED` or `SHIPPED`; the kit becomes `CANCELLED`, which is terminal, the parent complaint moves `AWAITING_SAMPLE → IN_RESOLUTION`, and the consumer's `open_kit_count` falls by one. Alternatively, the periodic quality checkpoint expires a `SHIPPED` kit once the logical clock is strictly after its `expected_return_by`: the kit becomes `EXPIRED`, its `disposition` is forced to `UNUSABLE` and its `chain_integrity_status` forced to `BROKEN`, the complaint again moves `AWAITING_SAMPLE → IN_RESOLUTION`, and `open_kit_count` falls by one. `LAB_ACCEPTED`, `EXPIRED`, and `CANCELLED` are all terminal, and any attempt to act on a kit in one of them — or on any kit whose current status does not permit the requested step — yields `ERR_SAMPLE_KIT_STATE_INVALID`.

### 3.6. Goodwill Remedies, Authority Tiers, the Consumer Ledger and Sentiment

Goodwill is the company's apology, and it is priced by rule rather than by negotiation. A `CareAgent` or `CareSupervisor` authors a remedy against a complaint by supplying the `complaint_id`, a `remedy_type` of `COUPON`, `REFUND`, or `REPLACEMENT`, a `requested_value_cents` between 1 and 999,999, and the `expected_complaint_version` revision pin from §2.7. The remedy's `consumer_id` is copied from the complaint, `authored_by_ref` is stamped from the acting staff identifier, `status` starts at `DRAFT`, `revision_count` starts at 0, and `kit_returned_credit_applied` starts as false. Authoring a new remedy on a complaint that already has a live one — one in `DRAFT`, `SUBMITTED`, or `REVISION_REQUESTED` — retires the older one to `SUPERSEDED`, so that at most one live remedy exists per complaint at any time.

The **goodwill computation** runs at authoring and is recomputed when the remedy is submitted, and its step order is pinned because it looks circular otherwise. First `base_value_cents` is established, and how depends entirely on the type. For a `COUPON`, the base is exactly `requested_value_cents`. For a `REFUND`, the base is `requested_value_cents` or the resolved lot's product `unit_retail_price_cents` multiplied by the complaint's `units_claimed`, whichever is smaller; and if the complaint's kit has reached `LAB_ACCEPTED`, a sample-return credit of 799 cents is then added to that capped figure and `kit_returned_credit_applied` is set true. For a `REPLACEMENT`, `requested_value_cents` is ignored entirely: the base is the product's `unit_retail_price_cents` multiplied by `units_claimed` or by 3, whichever is smaller, multiplied again by a handling factor of 1.15, and rounded half up to a whole number of cents.

Second, and this is the step that must not be reordered, `uplift_pct` is selected from `base_value_cents` **alone** and never from the payout it helps produce. A base below 1,000 cents draws 0.00; a base of 1,000 cents or more but below 5,000 cents draws 0.10; a base of 5,000 cents or more draws 0.05. The band is deliberately non-monotonic in the request, because the higher band carries the smaller rate: a base of 4,999 cents pays out 5,499 while a base of 5,000 cents pays out only 5,250. One practical consequence of the ordering is that the 799-cent sample-return credit is added *before* the band is chosen, so a returned kit can push a refund base across the 5,000-cent boundary and thereby *lower* the uplift rate that applies.

Third, `uplift_cents` is `base_value_cents` multiplied by `uplift_pct`, rounded half up to a whole number of cents, and `payout_cents` is `base_value_cents` plus `uplift_cents`. Fourth, `authority_tier_required` is banded from the final payout: `TIER_1` when `payout_cents` is at most 2,500, `TIER_2` when it is at most 7,500, and `TIER_3` above that. A `payout_cents` exceeding 25,000 is rejected outright with `ERR_GOODWILL_ABOVE_MAX`, and that ceiling is re-checked at authoring, at submission, and at decision time.

Submitting a remedy for approval, optionally with a `submit_note`, moves it `DRAFT → SUBMITTED` or `REVISION_REQUESTED → SUBMITTED` and recomputes the goodwill figures against the kit's current status. Submission from `DRAFT` additionally requires that the parent complaint is not in `ON_QUALITY_HOLD`, `RESOLVED`, `CLOSED`, or `DUPLICATE`; resubmission from `REVISION_REQUESTED` additionally requires that `revision_count` has not gone beyond the cap of 2 revisions.

A `CareSupervisor` or `QualityLead` decides a submitted remedy by supplying a `decision` of `APPROVE`, `REJECT`, or `REQUEST_REVISION`, optionally with a `decision_note`. Every one of the three decisions requires that the remedy is in `SUBMITTED` and that the deciding staff identifier differs from `authored_by_ref`; a decider who authored the remedy is refused with `ERR_SEGREGATION_OF_DUTIES` regardless of how much authority they hold. `REQUEST_REVISION` moves the remedy `SUBMITTED → REVISION_REQUESTED` and raises `revision_count` by one, and it additionally requires that `revision_count` is still strictly below the cap of 2; at the cap the supervisor must approve or reject instead, and a further revision attempt is refused with `ERR_REVISION_LIMIT_REACHED`. `REJECT` moves the remedy `SUBMITTED → REJECTED`, which is terminal, and stamps `decided_by_ref`. `APPROVE` moves it `SUBMITTED → APPROVED`, stamps `decided_by_ref`, and additionally requires two things: that the deciding staff member's `authority_tier` rank is at least the remedy's `authority_tier_required` rank, ranked `TIER_1` below `TIER_2` below `TIER_3`, failing which the decision is refused with `ERR_AUTHORITY_TIER_INSUFFICIENT`; and that the complaint's kit, if one exists, is not in `REQUESTED`, `SHIPPED`, or `IN_TRANSIT_INBOUND`, since goodwill is never approved while physical evidence is still in transit, failing which the decision is refused with `ERR_SAMPLE_KIT_IN_FLIGHT`. Approval raises the consumer's `goodwill_authorized_cents` and `goodwill_outstanding_cents` each by `payout_cents`.

Issuing the approved goodwill is a `CareSupervisor` action, optionally recording a `fulfilment_reference`. The remedy must be in `APPROVED` and the parent complaint must not be in `ON_QUALITY_HOLD`. Fulfilment moves the remedy `APPROVED → FULFILLED`, stamps `fulfilled_at`, moves `payout_cents` out of the consumer's `goodwill_outstanding_cents` and into `goodwill_paid_cents`, and — when the complaint has a resolved lot — raises that lot's `goodwill_charged_cents` by `payout_cents`.

Two reversal paths exist, and they touch different accounts. A `CareSupervisor` may void a remedy, optionally with a `reason`, from either `APPROVED` or `FULFILLED`, provided the parent complaint is not `CLOSED`; the remedy moves to `VOIDED_AFTER_FULFILLMENT`, which is terminal, `payout_cents` moves out of the consumer's `goodwill_paid_cents` and into `goodwill_voided_cents`, and the lot's `goodwill_charged_cents` is lowered by `payout_cents`. Separately, when a `QualityLead` imposes a quality hold on the complaint, every remedy on it in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, or `APPROVED` is moved to `VOIDED_BY_HOLD`; only for those that were in `APPROVED` is the ledger touched, moving `payout_cents` out of `goodwill_outstanding_cents` and into `goodwill_voided_cents`. Any attempt to submit, decide, fulfil, or void a remedy whose current `status` does not permit that step yields `ERR_REMEDY_STATE_INVALID`, and that state check is evaluated before the authority-tier check, so a remedy that is both in the wrong state and beyond the decider's tier reports the state problem.

Alongside the money, each consumer carries a `sentiment_index` between 0.00 and 100.00, recomputed on every read of their record and also exposed as a dedicated computed read. That read reports `consumer_id`, the `view` that was applied, a `penalty_total`, a `credit_total`, the resulting `sentiment_index`, and a `complaint_count_in_window`. The index starts from a neutral base of 50. Every complaint of that consumer that is not in `DUPLICATE` and whose `created_at` is no earlier than 180 days before the logical clock counts as in-window and contributes a penalty: 20 points for an `effective_severity_band` of `S1`, 12 for `S2`, 6 for `S3`, and 3 for `S4`, plus a surcharge of 5 further points whenever the complaint still has no `adjudicated_severity_score`. A complaint's age in days is the whole number of days between its `created_at` and the logical clock, discarding any fractional day. Two views differ in exactly one respect. Under the default agent view — used when a consumer record is read, and when the sentiment read omits `view` or sets it to `agent_view` — a complaint whose age has reached 90 days contributes half of its raw penalty, with the boundary inclusive so that a complaint exactly 90 days old already decays; younger complaints contribute their full penalty. Under `executive_view`, no decay applies and every in-window penalty counts at full weight. Credits are the same under both views: 8 points for each of the consumer's remedies in `FULFILLED`, plus 4 points for each in-window complaint whose `responded_at` has been set. The index is the neutral base of 50 minus the sum of all penalties plus the credits, rounded half up to 2 decimal places, and then clamped so that anything below 0.00 reads 0.00 and anything above 100.00 reads 100.00.

### 3.7. Regulatory Escalation, Determination and Agency Filing

Illness, adverse events and foreign-material injuries carry statutory reporting obligations, and the regulatory dimension exists to make those obligations visible and time-bounded. A report reaches existence in one of two ways: automatically, as one of the fan-out consequences of an `S1` or `S2` adjudication on an `ILLNESS` or `FOREIGN_MATERIAL` complaint; or manually, when a `RegulatoryOfficer` or `QualityLead` escalates a complaint by supplying its `complaint_id` and a `report_kind` of `ADVERSE_EVENT`, `ILLNESS_CLUSTER`, or `FOREIGN_MATERIAL_INJURY`. Either way the report opens in `OPEN`, `escalated_at` is set to the logical clock, and the complaint's `regulatory_status` advances `NOT_APPLICABLE → ESCALATED`. Escalation requires that the complaint is not in `DUPLICATE` and that no non-withdrawn report already exists for it; a second concurrent report is refused with `ERR_REPORT_ALREADY_OPEN`. At most one non-withdrawn report exists per complaint, and the `complaint_id` on a report is fixed once written.

The **submission deadline** is derived at escalation from the complaint's `effective_severity_band` at that moment: `due_at` is 24 hours after `escalated_at` when the band is `S1`, and 72 hours after `escalated_at` for every other band. Instants are compared at millisecond precision.

A `RegulatoryOfficer` — and only a `RegulatoryOfficer` — records the reportability verdict by supplying a `determination` of `REPORTABLE` or `NOT_REPORTABLE`, optionally with a `determination_note` capturing the rationale. The report must be in `OPEN`, otherwise `ERR_REPORT_STATE_INVALID`. A `REPORTABLE` verdict moves the report `OPEN → DETERMINED_REPORTABLE`, stamps `determined_by_ref` with the deciding officer, and advances the complaint `ESCALATED → REPORTABLE`. A `NOT_REPORTABLE` verdict moves the report `OPEN → DETERMINED_NOT_REPORTABLE`, likewise stamps `determined_by_ref`, and advances the complaint `ESCALATED → NOT_REPORTABLE` — but only when the complaint's `effective_severity_band` is not `S1`. The most severe band can never be determined non-reportable, and the attempt is refused with `ERR_S1_MUST_BE_REPORTABLE`.

Filing with the agency requires an `agency_reference`, the acknowledgement reference the agency returns, and it is the point where segregation of duties bites a second time. The report must be in `DETERMINED_REPORTABLE`, and the submitting staff identifier must differ from `determined_by_ref`; the same officer may not both determine and file the same report, and the attempt is refused with `ERR_SEGREGATION_OF_DUTIES`. Filing moves the report `DETERMINED_REPORTABLE → SUBMITTED`, which is terminal, stamps `submitted_by_ref` and `submitted_at` from the logical clock, advances the complaint `REPORTABLE → SUBMITTED`, and computes `submitted_late` as true when `submitted_at` is **strictly after** `due_at`. Filing at exactly `due_at` is on time, and `submitted_late` reads as unset until a filing actually happens.

A report that has not been filed may be withdrawn, optionally with a `reason`, from `OPEN`, from `DETERMINED_REPORTABLE`, or from `DETERMINED_NOT_REPORTABLE`. Withdrawal moves the report to `WITHDRAWN`, which is terminal, and resets the complaint's `regulatory_status` all the way back to `NOT_APPLICABLE` — from `ESCALATED`, from `REPORTABLE`, or from `NOT_REPORTABLE` alike — which is precisely what makes a fresh escalation possible afterwards. A report already in `SUBMITTED` or `WITHDRAWN` cannot be withdrawn again. Reports may be listed filtered by `submitted_late` among other criteria.

### 3.8. Templated Consumer Response, Resolution and Closure

The words the company sends back to a consumer are controlled centrally. A `CareSupervisor` drafts a response template with a unique `template_code`, a `title`, a `body` of 1 to 4,000 characters, an `applies_to_type` naming the complaint type it may answer — `FOREIGN_MATERIAL`, `ILLNESS`, `PACKAGING`, `QUALITY`, or `ANY` to match all types — and a `max_band_allowed` naming the most severe band it may answer, where `S1` is the most severe and `S4` the least. A `requires_supervisor_approval` boolean defaults to false; when it is true, only a `CareSupervisor` may send that template. Templates start in `DRAFT` with a `usage_count` of 0. A supervisor publishes a template `DRAFT → ACTIVE` and later retires it `ACTIVE → RETIRED`, which is terminal; a retired template can never be selected for a response again. Activating or retiring a template whose `status` does not permit that step yields `ERR_TEMPLATE_STATE_INVALID`.

Sending the response is a `CareAgent` or `CareSupervisor` action carrying the `response_template_id` of the chosen template. The complaint must be in `TRIAGED`, and three referential rules are checked in a fixed order. First, the complaint's linked lot must not be `WITHDRAWN` — once a lot is withdrawn, canned consumer messaging about it is frozen, and the attempt fails with `ERR_LOT_WITHDRAWN`. Because that check is ranked above the template rules, a withdrawn lot masks any template problem in the same request. Second, the chosen template must be `ACTIVE`, failing which the response is refused with `ERR_TEMPLATE_STATE_INVALID`, and its `applies_to_type` must be either the complaint's `complaint_type` or `ANY`, failing which the response is refused with `ERR_TEMPLATE_TYPE_MISMATCH`. Third, the template's `max_band_allowed` must be no less severe than the complaint's `effective_severity_band`; a mild-band template cannot answer a severe complaint, and the mismatch is refused with `ERR_TEMPLATE_BAND_TOO_LOW`. A successful response moves the complaint `TRIAGED → IN_RESOLUTION`, sets `responded_template_id` to the chosen template and `responded_at` to the logical clock, and raises the template's `usage_count` by one.

A complaint can also reach `IN_RESOLUTION` without a response having been sent, because kit acceptance, kit cancellation and kit expiry all move it `AWAITING_SAMPLE → IN_RESOLUTION`. Resolution therefore checks for the response explicitly. A `CareAgent` or `CareSupervisor` resolves a complaint, optionally recording a `resolution_note`, moving it `IN_RESOLUTION → RESOLVED`; that requires the complaint to be in `IN_RESOLUTION`, to have a `responded_at` on file, and to have no remedy left in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, or `APPROVED` — every goodwill offer must have been fulfilled, rejected, superseded, or voided first.

Final closure belongs to a `CareSupervisor` alone, optionally with a `closing_note`. It moves the complaint `RESOLVED → CLOSED`, which is terminal in the handling dimension and after which no handling transition of any kind is permitted. Closure is the one point where the two dimensions of §2.10 meet: it requires that `regulatory_status` has settled into `NOT_APPLICABLE`, `NOT_REPORTABLE`, or `SUBMITTED`. A complaint still sitting in `ESCALATED` or `REPORTABLE` cannot be closed, and the attempt is refused with `ERR_REGULATORY_STATE_INVALID`.

A quality investigation can interrupt this whole arc. A `QualityLead` freezes a complaint that is in `TRIAGED`, `AWAITING_SAMPLE`, or `IN_RESOLUTION`, optionally with a `reason`: the departing state is recorded in `pre_hold_handling_status` and the complaint moves to `ON_QUALITY_HOLD`, voiding every live remedy on it as described in §3.6. Releasing the hold, again a `QualityLead` action with an optional `reason`, returns the complaint from `ON_QUALITY_HOLD` to exactly the state recorded in `pre_hold_handling_status` and then clears that field. Release is blocked while any trend signal containing this complaint sits in `RECALL_EVALUATION`; a complaint under live recall evaluation stays on hold and the attempt is refused with `ERR_RECALL_EVALUATION_ACTIVE`.

### 3.9. Complaint-Rate Monitoring, Trend Signals, Investigation and Recall

Individual complaints are anecdotes; rates per million units are evidence. Reading a lot's rate reports `production_lot_id`, the `variant` applied, the `numerator` used, the lot's `units_produced`, the resulting `rate_ppm`, and a `rate_undefined` flag. The `provisional` variant — the default, used when `variant` is omitted or set to `provisional` — counts every complaint linked to the lot whose `handling_status` is not `DUPLICATE`, triaged or not. The `adjudicated` variant counts only those non-duplicate linked complaints that carry an `adjudicated_severity_score`. In both variants, when `units_produced` is 0 the rate is reported as 0.00 with `rate_undefined` true, and no division is attempted and no error is raised; otherwise `rate_ppm` is the numerator divided by `units_produced`, multiplied by one million, rounded half up to 2 decimal places, with `rate_undefined` false.

**Trend detection** is severity-weighted and windowed. The detection window is the 30 days ending at the logical clock, and it is **half-open** on a complaint's `created_at`: a complaint counts when its `created_at` is at or after the window's start and strictly before the window's end. A complaint is eligible only when it has a resolved `lot_id` and its `handling_status` is not `DUPLICATE`. Each eligible complaint contributes a severity weight determined by its `effective_severity_band` — 3 for `S1`, 2 for `S2`, 1 for `S3`, and 0 for `S4`. For a given scope, `weighted_complaint_count` is the sum of those weights carried to 2 decimal places, and `units_in_scope` is the sum of `units_produced` over the lots in that scope. The `observed_rate_ppm` is 0.00 when `units_in_scope` is 0, and otherwise `weighted_complaint_count` divided by `units_in_scope`, multiplied by one million, rounded half up to 2 decimal places. A scope fires when **both** conditions hold, each comparison inclusive: `weighted_complaint_count` is at least 3.0, and `observed_rate_ppm` is at least the `threshold_ppm` for that scope level — 25.0 for `LOT`, 12.0 for `LINE`, and 6.0 for `PLANT`.

The periodic quality checkpoint applies these tests in a **narrowest-scope-wins waterfall**, so that no complaint is ever counted into two signals. Lots are examined first, in ascending order of `code_date` and then `created_at`; each lot that fires emits a signal and consumes its own complaints and units. Lines are examined next, in ascending order of `line_code` and then `created_at`, each evaluated over only the complaints and units not already consumed; a line that fires emits a signal and consumes what remains in its scope. Plants are examined last, in ascending order of `plant_code` and then `created_at`, again over the unconsumed remainder. Each emitted signal records its `scope_level`, the `plant_id` (always populated, whatever the scope), the `production_line_id` and `lot_id` where the scope has them, the `window_start` and `window_end` that were tested, the computed `weighted_complaint_count`, `units_in_scope`, `observed_rate_ppm`, and the `threshold_ppm` it was compared against, a `detection_source` of `OPS_RUN`, a `membership_count`, and a `status` of `DETECTED`. For every contributing complaint the checkpoint inserts an immutable membership record naming the `trend_signal_id` and `complaint_id`, stamped with the `severity_weight` that complaint contributed at the moment of detection and an `included_variant` of `ADJUDICATED` when the complaint had an `adjudicated_severity_score` and `PROVISIONAL` when it did not. Each complaint's `linked_signal_count` reflects how many memberships reference it. If a signal for the identical scope key and the identical window already exists in `DETECTED`, it is refreshed in place rather than duplicated.

A `QualityLead` may also raise a signal by hand for one explicit scope, supplying the `scope_level`, the `plant_id`, the `window_start` and `window_end`, and the `production_line_id` and `lot_id` that the scope shape requires. A manual signal records `detection_source` `MANUAL` and computes its weighted count, units, observed rate and threshold from the complaints actually inside the declared window — for that single declared scope only, with **no waterfall**. The `window_end` must be strictly after `window_start`, otherwise `ERR_WINDOW_INVALID`. The scope shape must be internally consistent — a `LOT` scope names both the line and the lot, a `LINE` scope names the line and leaves the lot empty, and a `PLANT` scope leaves both empty — otherwise `ERR_SCOPE_SHAPE_INVALID`. The window must not strictly overlap an existing `DETECTED`, `INVESTIGATION_OPEN`, or `RECALL_EVALUATION` signal for the same scope key, otherwise `ERR_SIGNAL_WINDOW_OVERLAP`; since the windows are half-open, two that merely touch at a boundary may coexist. And a manual window containing no eligible complaint at all is refused with `ERR_SIGNAL_EMPTY_MEMBERSHIP`.

From `DETECTED`, a `QualityLead` takes one of two paths. Dismissing the signal as noise, optionally with a `reason`, moves it `DETECTED → DISMISSED`, which is terminal, and re-derives the plant's `oversight_posture`. Opening an investigation, optionally with an `investigation_note`, moves it `DETECTED → INVESTIGATION_OPEN`, stamps `opened_by_ref`, raises the plant's `open_investigation_count` by one, and re-derives the plant's posture to `WATCH` or `INVESTIGATION_HOLD` per §2.8. Opening an investigation requires `membership_count` of at least 1; a signal with no members is refused with `ERR_SIGNAL_EMPTY_MEMBERSHIP`.

Escalating an open investigation to recall evaluation, optionally with an `escalation_note`, moves the signal `INVESTIGATION_OPEN → RECALL_EVALUATION` and requires that at least one member complaint has an `effective_severity_band` of `S1` or `S2`; low-severity trends are investigated but never escalated, and the attempt otherwise fails with `ERR_SEVERITY_TOO_LOW_FOR_RECALL`. Escalation is the widest cascade in the system. Every member complaint not already in `RESOLVED`, `CLOSED`, or `DUPLICATE` is moved to `ON_QUALITY_HOLD`, recording its departing state in `pre_hold_handling_status` and voiding its live remedies with the consumer goodwill ledger reconciled exactly as in §3.6. Every lot in scope is placed on hold: for a `LOT`-scope signal that is the single named lot, and for `LINE`- and `PLANT`-scope signals it is every lot in scope currently in `RELEASED`, each moving `RELEASED → HOLD`. The plant's `oversight_posture` is then forced to `INVESTIGATION_HOLD`, which is what blocks new lot registration for that plant's lines.

Two outcomes close the matter. Closing without action, optionally with a `closing_note`, is available from either `INVESTIGATION_OPEN` or `RECALL_EVALUATION` and moves the signal to `CLOSED_NO_ACTION`, which is terminal; it lowers the plant's `open_investigation_count` by one, re-derives the plant's posture, and returns to `RELEASED` those lots that were placed on hold by this signal alone. Initiating the recall requires a `recall_reference` and is available only from `RECALL_EVALUATION`; it moves the signal to `RECALL_INITIATED`, which is terminal, moves every lot in scope to `WITHDRAWN`, raises the plant's `recall_initiated_count` by one, and holds the plant's `oversight_posture` at `INVESTIGATION_HOLD`. A recall may not precede the regulatory filings it depends on: every member complaint whose `regulatory_status` is `REPORTABLE` must already have a report in `SUBMITTED`, failing which the initiation is refused with `ERR_REGULATORY_SUBMISSION_PENDING`. Any transition attempted from a signal `status` that does not permit it yields `ERR_TREND_SIGNAL_STATE_INVALID`.

The **quality operations checkpoint** ties the temporal work together. A `QualityLead` runs it against the current logical clock, optionally passing `dry_run`. A live run expires every `SHIPPED` kit whose `expected_return_by` the clock has passed and advances the affected complaints out of `AWAITING_SAMPLE`, re-runs lot rate computation, executes the narrowest-scope-wins waterfall to create or refresh signals together with their memberships, and re-derives `oversight_posture` for every affected plant. The run reports the `run_at` instant it used along with `kits_expired_count`, `complaints_advanced_count`, `signals_created_count`, `signals_refreshed_count`, `memberships_created_count`, and `plants_reposted_count`. With `dry_run` set to true the identical counts are returned and nothing at all is persisted.

## 4. Endpoint Definitions

Operations that bring a new, independently addressable resource into existence — a staff user, a consumer, a plant, a line, a product, a lot, a contact, a complaint, a sample kit, a custody event, a remedy, a regulatory report, a trend signal, a response template — return `201 Created`. Every other operation, including all state transitions, all partial updates, all computed reads, the logical-clock write and the operations checkpoint, returns `200 OK`. Errors carry the HTTP status listed in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | SystemAdmin |
| POST | `/staff-users` | Register an internal actor | SystemAdmin |
| GET | `/staff-users` | List staff | SystemAdmin |
| GET | `/staff-users/{id}` | Fetch one staff member | SystemAdmin |
| POST | `/consumers` | Create a consumer record | CareAgent, CareSupervisor |
| GET | `/consumers` | List consumers | CareAgent, CareSupervisor, QualityLead |
| GET | `/consumers/{id}` | Fetch one consumer, recomputing sentiment on read | CareAgent, CareSupervisor, QualityLead, Consumer |
| PATCH | `/consumers/{id}` | Update mutable consumer contact details | CareAgent, CareSupervisor |
| GET | `/consumers/{id}/sentiment` | Computed sentiment read with a selectable variant | CareSupervisor, QualityLead |
| POST | `/plants` | Create a plant | SystemAdmin |
| GET | `/plants` | List plants | SystemAdmin, QualityLead, CareSupervisor |
| GET | `/plants/{id}` | Fetch one plant with its derived oversight posture | SystemAdmin, QualityLead, CareSupervisor |
| POST | `/production-lines` | Create a production line under a plant | SystemAdmin |
| GET | `/plants/{id}/production-lines` | List the lines of one plant | SystemAdmin, QualityLead, CareSupervisor |
| GET | `/production-lines/{id}` | Fetch one production line | SystemAdmin, QualityLead, CareSupervisor |
| POST | `/products` | Create a product SKU | SystemAdmin |
| GET | `/products` | List products | SystemAdmin, QualityLead, CareSupervisor, CareAgent |
| GET | `/products/{id}` | Fetch one product | SystemAdmin, QualityLead, CareSupervisor, CareAgent |
| POST | `/production-lots` | Register a production lot | SystemAdmin, QualityLead |
| GET | `/production-lots` | List production lots with filters | SystemAdmin, QualityLead, CareSupervisor, CareAgent |
| GET | `/production-lots/{id}` | Fetch one lot with its complaint buckets and goodwill ledger | SystemAdmin, QualityLead, CareSupervisor, CareAgent |
| GET | `/production-lots/{id}/complaint-rate` | Computed complaints-per-million-units read for one lot | QualityLead, CareSupervisor |
| POST | `/production-lots/{id}/hold` | Place a lot on quality hold | QualityLead |
| POST | `/production-lots/{id}/release` | Return a held lot to trade | QualityLead |
| POST | `/production-lots/{id}/withdraw` | Withdraw a held lot from trade permanently | QualityLead |
| POST | `/contacts` | Log an inbound consumer contact on one channel | CareAgent, CareSupervisor |
| GET | `/contacts` | List contacts with filters | CareAgent, CareSupervisor, QualityLead |
| GET | `/contacts/{id}` | Fetch one contact | CareAgent, CareSupervisor, QualityLead |
| POST | `/contacts/{id}/close-no-complaint` | Close a contact that produced no complaint | CareAgent, CareSupervisor |
| POST | `/complaints` | Create a categorized complaint from a contact | CareAgent, CareSupervisor |
| GET | `/complaints` | List complaints with filters across every relationship | CareAgent, CareSupervisor, QualityLead, RegulatoryOfficer |
| GET | `/complaints/{id}` | Fetch one complaint with both dimensions and both severity variants | CareAgent, CareSupervisor, QualityLead, RegulatoryOfficer |
| POST | `/complaints/{id}/identify-product` | Re-run batch-code resolution with a corrected code | CareAgent, CareSupervisor |
| POST | `/complaints/{id}/triage` | Adjudicate severity and fan out the consequences | CareSupervisor, QualityLead |
| POST | `/complaints/{id}/respond` | Send a templated consumer response | CareAgent, CareSupervisor |
| POST | `/complaints/{id}/mark-duplicate` | Mark this complaint a duplicate of another | CareSupervisor |
| POST | `/complaints/{id}/unmark-duplicate` | Restore a complaint wrongly marked a duplicate | CareSupervisor |
| POST | `/complaints/{id}/quality-hold` | Freeze a complaint for quality investigation | QualityLead |
| POST | `/complaints/{id}/release-hold` | Return a complaint from quality hold to its pre-hold state | QualityLead |
| POST | `/complaints/{id}/resolve` | Mark the complaint resolved | CareAgent, CareSupervisor |
| POST | `/complaints/{id}/close` | Close the complaint permanently | CareSupervisor |
| GET | `/complaints/{id}/signal-memberships` | List the trend-signal memberships this complaint contributed to | CareSupervisor, QualityLead |
| POST | `/sample-kits` | Request a sample-retrieval kit for a triaged complaint | CareAgent, CareSupervisor |
| GET | `/sample-kits` | List sample kits with filters | CareAgent, CareSupervisor, QualityLead |
| GET | `/sample-kits/{id}` | Fetch one sample kit with its custody projection | CareAgent, CareSupervisor, QualityLead |
| POST | `/sample-kits/{id}/ship` | Dispatch the kit to the consumer | CareAgent, CareSupervisor |
| POST | `/sample-kits/{id}/receive` | Log the kit as physically received by the lab | QualityLead |
| POST | `/sample-kits/{id}/lab-accept` | Accept the kit into the lab and set its disposition | QualityLead |
| POST | `/sample-kits/{id}/cancel` | Cancel an unreturned kit | CareSupervisor |
| POST | `/sample-kits/{id}/custody-events` | Append one immutable chain-of-custody record | CareAgent, CareSupervisor, QualityLead |
| GET | `/sample-kits/{id}/custody-events` | List a kit's custody chain in sequence order | CareAgent, CareSupervisor, QualityLead |
| POST | `/remedies` | Author a goodwill remedy against a complaint | CareAgent, CareSupervisor |
| GET | `/remedies` | List remedies with filters | CareAgent, CareSupervisor, QualityLead |
| GET | `/remedies/{id}` | Fetch one remedy with its full goodwill computation | CareAgent, CareSupervisor, QualityLead |
| POST | `/remedies/{id}/submit` | Submit a draft or revised remedy for approval | CareAgent, CareSupervisor |
| POST | `/remedies/{id}/decide` | Approve, reject or send back a submitted remedy | CareSupervisor, QualityLead |
| POST | `/remedies/{id}/fulfill` | Issue the approved goodwill | CareSupervisor |
| POST | `/remedies/{id}/void` | Reverse an approved or already fulfilled remedy | CareSupervisor |
| POST | `/regulatory-reports` | Manually escalate a complaint to regulatory | RegulatoryOfficer, QualityLead |
| GET | `/regulatory-reports` | List regulatory reports with filters | RegulatoryOfficer, QualityLead, CareSupervisor |
| GET | `/regulatory-reports/{id}` | Fetch one report with its deadline and lateness verdict | RegulatoryOfficer, QualityLead, CareSupervisor |
| POST | `/regulatory-reports/{id}/determine` | Record the reportability determination | RegulatoryOfficer |
| POST | `/regulatory-reports/{id}/submit` | File the report with the agency | RegulatoryOfficer |
| POST | `/regulatory-reports/{id}/withdraw` | Withdraw an unsubmitted report | RegulatoryOfficer |
| POST | `/trend-signals` | Manually raise a trend signal for an explicit scope and window | QualityLead |
| GET | `/trend-signals` | List trend signals with filters | QualityLead, CareSupervisor, RegulatoryOfficer |
| GET | `/trend-signals/{id}` | Fetch one trend signal | QualityLead, CareSupervisor, RegulatoryOfficer |
| GET | `/trend-signals/{id}/memberships` | List the complaints that constitute one signal | QualityLead, CareSupervisor, RegulatoryOfficer |
| POST | `/trend-signals/{id}/open-investigation` | Open a quality investigation on a detected signal | QualityLead |
| POST | `/trend-signals/{id}/dismiss` | Dismiss a detected signal as noise | QualityLead |
| POST | `/trend-signals/{id}/escalate-recall-evaluation` | Escalate an investigation to recall evaluation | QualityLead |
| POST | `/trend-signals/{id}/initiate-recall` | Initiate the recall | QualityLead |
| POST | `/trend-signals/{id}/close-no-action` | Close an investigation or recall evaluation without action | QualityLead |
| POST | `/response-templates` | Draft a consumer-response template | CareSupervisor |
| GET | `/response-templates` | List response templates | CareAgent, CareSupervisor, QualityLead |
| GET | `/response-templates/{id}` | Fetch one response template | CareAgent, CareSupervisor, QualityLead |
| POST | `/response-templates/{id}/activate` | Publish a template for use | CareSupervisor |
| POST | `/response-templates/{id}/retire` | Retire a published template | CareSupervisor |
| POST | `/quality-ops-runs` | Run the periodic quality checkpoint | QualityLead |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNKNOWN_ACTOR` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_AUTHORITY_TIER_INSUFFICIENT` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STAFF_USER_NOT_FOUND` | 404 Not Found |
| `ERR_CONSUMER_NOT_FOUND` | 404 Not Found |
| `ERR_PLANT_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCTION_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCTION_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTACT_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLAINT_NOT_FOUND` | 404 Not Found |
| `ERR_SAMPLE_KIT_NOT_FOUND` | 404 Not Found |
| `ERR_REMEDY_NOT_FOUND` | 404 Not Found |
| `ERR_REGULATORY_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_TREND_SIGNAL_NOT_FOUND` | 404 Not Found |
| `ERR_RESPONSE_TEMPLATE_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_CONTACT_CLOSED` | 409 Conflict |
| `ERR_CONTACT_HAS_COMPLAINTS` | 409 Conflict |
| `ERR_COMPLAINT_STATE_INVALID` | 409 Conflict |
| `ERR_REGULATORY_STATE_INVALID` | 409 Conflict |
| `ERR_REPORT_ALREADY_OPEN` | 409 Conflict |
| `ERR_REMEDY_STATE_INVALID` | 409 Conflict |
| `ERR_SAMPLE_KIT_STATE_INVALID` | 409 Conflict |
| `ERR_TREND_SIGNAL_STATE_INVALID` | 409 Conflict |
| `ERR_LOT_STATE_INVALID` | 409 Conflict |
| `ERR_TEMPLATE_STATE_INVALID` | 409 Conflict |
| `ERR_REPORT_STATE_INVALID` | 409 Conflict |
| `ERR_PRODUCT_UNIDENTIFIED` | 409 Conflict |
| `ERR_LOT_WITHDRAWN` | 409 Conflict |
| `ERR_RECALL_EVALUATION_ACTIVE` | 409 Conflict |
| `ERR_SIGNAL_INVESTIGATION_ACTIVE` | 409 Conflict |
| `ERR_REGULATORY_SUBMISSION_PENDING` | 409 Conflict |
| `ERR_SAMPLE_KIT_IN_FLIGHT` | 409 Conflict |
| `ERR_PLANT_UNDER_INVESTIGATION_HOLD` | 409 Conflict |
| `ERR_KIT_INTERVAL_CONFLICT` | 409 Conflict |
| `ERR_SIGNAL_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_REVISION_LIMIT_REACHED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_STALE_COMPLAINT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SAMPLE_KIT_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_TARGET_INVALID` | 422 Unprocessable Entity |
| `ERR_S1_MUST_BE_REPORTABLE` | 422 Unprocessable Entity |
| `ERR_SEVERITY_TOO_LOW_FOR_RECALL` | 422 Unprocessable Entity |
| `ERR_SIGNAL_EMPTY_MEMBERSHIP` | 422 Unprocessable Entity |
| `ERR_RECEIVED_AT_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_CUSTODY_OUT_OF_ORDER` | 422 Unprocessable Entity |
| `ERR_CUSTODY_SEQUENCE_INVALID` | 422 Unprocessable Entity |
| `ERR_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_SCOPE_SHAPE_INVALID` | 422 Unprocessable Entity |
| `ERR_CONSUMER_ADDRESS_MISSING` | 422 Unprocessable Entity |
| `ERR_TEMPLATE_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TEMPLATE_BAND_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_GOODWILL_ABOVE_MAX` | 422 Unprocessable Entity |
| `ERR_BATCH_CODE_AMBIGUOUS` | 422 Unprocessable Entity |
