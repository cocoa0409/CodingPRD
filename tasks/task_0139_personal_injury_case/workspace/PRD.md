# Personal Injury Case API — Product Requirements Document

## 1. Introduction

Plaintiff-side personal injury law firms operate at the intersection of medical evidence-gathering, multi-party settlement negotiation, statutory deadlines, and strict fiduciary controls over client funds. A single matter routinely involves a paralegal chasing records from multiple providers, an attorney drafting and revising a demand letter, weeks of back-and-forth offers between the firm and a defense carrier, court calendar entries that compete for an attorney's time, statutory and contractual liens jockeying for repayment priority, and ultimately a managing partner who must independently sign off on the disbursement waterfall before any money reaches the client. When any one of these workstreams loses synchronization with the others, the firm faces real risk: a stale damages number in an outgoing demand, a missed jurisdictional deadline, or an attorney who simultaneously negotiated and approved a payout to themselves.

This document specifies a case-management API that unifies these workstreams under a single source of truth. The system is responsible for tracking each case through its lifecycle from intake to closed disbursement, computing the statute-of-limitations cutoff per jurisdiction, valuing damages from received medical records, enforcing segregation of duties between the negotiator and the approver, and resolving the cents-exact waterfall that converts a gross settlement into checks issued to the client, lienholders, the firm, and recoverable case costs. All resources are mounted under the API prefix `/pi-cases` (with peer roots for client intake and administrative test-driving endpoints).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the calling user, and `X-User-Role`, naming the user's role. If either header is missing or empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401). If `X-User-Role` carries a value that is not in the declared role catalog, the request is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401). If the role is recognized but is not authorized for the requested endpoint (per the RBAC implied by §4 and the workflow narratives in §3), the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The role catalog contains exactly three values, spelled as shown: `Paralegal`, `Attorney`, and `ManagingPartner`. The `Paralegal` role is responsible for client intake paperwork, medical-records workflow, and the lien-negotiation outreach steps. The `Attorney` role drafts and sends demand letters, conducts settlement negotiation, manages the court calendar, and disputes liens. The `ManagingPartner` role approves final disbursement, dismisses cases, applies tolling to a case's statute deadline, and runs the administrative sweeps.

All three roles use **opaque** identity semantics: `X-User-ID` is an opaque operator identifier and the server does not compare it to any entity's `id` for ownership purposes. The server may record the supplied id in domain fields where a transition writes it — for example, the `ManagingPartner` who approves disbursement has their `X-User-ID` copied into `Case.disbursement_approved_by` and into `SettlementDisbursement.approved_by` — but it does not treat any entity's primary key as the operator's id. The one place this opaque identity is compared, narrowly and by design, is the segregation-of-duties check at disbursement approval (§3 and validation priority 31).

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

List endpoints accept two query parameters, `limit` and `offset`, that control the page being returned. The `limit` parameter defaults to 10 when not provided, has a minimum permitted value of 1, and a maximum permitted value of 100. The `offset` parameter defaults to 0 and may be any non-negative integer. List endpoints sort their results in ascending `created_at` order unless a specific endpoint description in §3 calls out a different ordering (for example, settlement offers are returned ordered by `round_number` then `created_at`). Every list response surfaces `limit`, `offset`, `total_count`, and `has_more` inside the `meta` envelope.

### 2.4. Resource Identity, Timestamps, Versioning, and Optimistic Concurrency

Every persisted resource is identified by a server-minted `id` that is a UUID string with no type prefix. Most resources also carry the `created_at` timestamp (when the row was first inserted), the `updated_at` timestamp (refreshed on every mutation), and an integer `version` that starts at 1 and increments by one each time the row is mutated. All timestamps are ISO 8601 UTC values formatted with three fractional digits. Two entities are intentionally exceptions to this pattern: `ContingencyFeeAgreement` is immutable after creation and `SettlementDisbursement` is created once and never revised, so both carry only `id` and `created_at` — they expose neither `updated_at` nor `version`.

Optimistic concurrency control is offered on every `PATCH` endpoint. Clients may include `version` in the request body to assert the version they expect to be updating; if the supplied `version` does not equal the stored `version`, the request is rejected with `ERR_VERSION_MISMATCH` (HTTP 409). Omitting `version` from the body skips the concurrency check entirely and the patch proceeds against whatever the current stored row is. The `version` is purely an integer counter — it has no semantic relationship to other fields.

### 2.5. Money, Time, and Precision

All monetary fields are integer cents, never decimals. Names such as `face_amount_cents`, `negotiated_amount_cents`, `final_paid_amount_cents`, `billed_amount_cents`, `medical_bills_cents`, `lost_wages_cents`, `property_damage_cents`, `pain_suffering_cents`, `total_damages_cents`, `demanded_amount_cents`, `snapshot_total_damages_cents`, `amount_cents`, `per_diem_rate_cents`, `gross_settlement_cents`, `case_costs_cents`, `gross_amount_cents`, `attorney_fee_cents`, `total_lien_payment_cents`, `client_net_cents`, and `award_amount_cents` all share this convention.

Where calculations require rounding (notably damages multiplied by a fractional multiplier, attorney fees expressed as basis points, and the lien waterfall's per-lien shares), the system applies **round half up** to the nearest integer cent. Banker's rounding is explicitly not used. Contingency fee rates are expressed in basis points (a basis point is one ten-thousandth) — the values `pre_suit_rate_bps`, `post_suit_rate_bps`, and `trial_rate_bps` are integers, and a rate is converted to a multiplier by dividing by 10,000 at the point of application. Statute-of-limitations deadlines (`sol_deadline`) are stored as whole calendar dates in the form `YYYY-MM-DD`, and the tolling accumulator `sol_tolled_days` is a count of whole calendar days. Court-event durations (`duration_minutes`) and the attorney-calendar travel buffer are expressed in whole minutes.

### 2.6. Hierarchical State Consistency and Cascades

The case is the central aggregate; medical-record requests, damages, liens, demand letters, settlement offers, court events, the contingency-fee agreement, and the disbursement record are all attached to a case. A mutation on a child resource that drives the parent across a state-machine edge is responsible for executing every cascade hop defined in §3 in the listed order, refreshing each affected row's `updated_at` and bumping each affected row's `version`. For example, marking the last outstanding medical-record request as `RECEIVED` recomputes `Damages.medical_bills_cents` and `Damages.total_damages_cents` (bumping `Damages.version`) and then flips `Case.status` from `RECORDS_PENDING` to `READY_FOR_DEMAND` (bumping `Case.version`). Cascades are atomic with respect to the triggering request: either every hop lands or none of them do.

### 2.7. Nested Resource Resolution

Child resources are addressed under their parent case in the URL (for example, a lien is reached through a path that includes the parent case id and then the lien id). The server resolves path parameters strictly left-to-right: it first checks that the case id refers to an existing case, and only then checks that the named child id refers to an existing child of that case. Any failure of an existence check returns `ERR_NOT_FOUND` (HTTP 404). Foreign keys carried in the request body (such as `client_id` when opening a case, `assigned_attorney_id` when assigning an attorney, or `predecessor_offer_id` when registering a counter offer) are validated separately and, if absent, are rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

### 2.8. Validation Priority and Evaluation Order

When more than one validation rule could potentially fire on the same request, the rules are evaluated in a strict priority order, lowest priority number first. Authentication checks run before role checks, which run before existence checks, which run before state-machine preconditions, which run before business-safety rules, which run before referential and constraint rules, which run before temporal and fiscal rules, and the optimistic-concurrency check runs last of all. Concretely: missing headers (`ERR_MISSING_AUTH_HEADERS`) is detected before an unknown role (`ERR_UNKNOWN_ROLE`), which is detected before a forbidden role (`ERR_FORBIDDEN`); resource existence (`ERR_NOT_FOUND`) and FK existence (`ERR_REFERENCE_NOT_FOUND`) come next; then the generic state precondition `ERR_INVALID_STATE` and its specific siblings (`ERR_CASE_CLOSED`, `ERR_DEMAND_NOT_DRAFT`, `ERR_OFFER_NOT_PENDING`, `ERR_CASE_INVALID_STATE`); then the safety rules — statute-of-limitations expiry (`ERR_STATUTE_OF_LIMITATIONS_EXPIRED`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), and stale-damages snapshot (`ERR_STALE_DAMAGES_SNAPSHOT`); then the referential, constraint, temporal, and fiscal rules; and finally `ERR_VERSION_MISMATCH`. A request that fails more than one check surfaces only the highest-priority error.

### 2.9. Concurrency and Serialization Guarantees

The API offers strong serialization on a small set of well-defined races. When two `Attorney` operators both attempt to flip the same `PENDING` settlement offer to `ACCEPTED` simultaneously, exactly one acceptance wins on a first-writer-wins basis at the `SettlementOffer.status` transition out of `PENDING`; the loser sees `ERR_OFFER_NOT_PENDING` (HTTP 409). When two paralegals try to insert the singleton `Damages` row for the same case at the same moment, the second insert is rejected with `ERR_DAMAGES_ALREADY_EXISTS` (HTTP 409). When two operators try to create the singleton `ContingencyFeeAgreement` row for the same case at the same moment, the second insert is rejected with `ERR_FEE_AGREEMENT_ALREADY_EXISTS` (HTTP 409). When two `ManagingPartner` operators both call disbursement approval against the same case, exactly one approval is recorded — first-writer-wins on `Case.disbursement_approved_by` transitioning from null — and the loser sees `ERR_DISBURSEMENT_ALREADY_APPROVED` (HTTP 409). When an offer-acceptance attempt races the statute-of-limitations expiry sweep that just moved the case to `DISMISSED`, the sweep commits first and acceptance loses because the case is no longer in `NEGOTIATING` or `LITIGATION`; the acceptance request is rejected with `ERR_CASE_INVALID_STATE` (HTTP 409). When two attorneys both attempt to send the same `DRAFT` demand letter, exactly one send wins on a first-writer-wins basis at the `DemandLetter.status` transition out of `DRAFT`, and the loser sees `ERR_DEMAND_NOT_DRAFT` (HTTP 409). When two court events with overlapping schedules are inserted against the same assigned attorney, the second insert is rejected with `ERR_ATTORNEY_CALENDAR_CONFLICT` (HTTP 409).

### 2.10. Statute of Limitations as a Hard Boundary

A case carries a computed `sol_deadline` from the moment it is opened. The deadline is a hard boundary: from the instant the server's current time reaches or passes `sol_deadline`, every state-advancing mutation on the case is blocked with `ERR_STATUTE_OF_LIMITATIONS_EXPIRED` (HTTP 422). The comparison is inclusive on the boundary — a request that arrives at exactly the deadline is already too late. The only operation that remains available on an out-of-statute case is dismissal by a `ManagingPartner`. A daily statute sweep run by a `ManagingPartner` examines every non-terminal case and, for any case whose `sol_deadline` is on or before the current server time, flips that case's `status` to `DISMISSED` and emits an audit-log entry tagged `sol_expired`.

## 3. Business Logic & Workflows

### 3.1. Client Intake and Opening a Case

A client record is created first, before any case. The intake step captures `full_name`, `date_of_birth`, `contact_email`, and `state_of_residence`. The date of birth must be a valid ISO 8601 calendar date in the past; the contact email must be a syntactically valid email address; and the state of residence is a two-letter uppercase US state code. The flag `is_minor_at_incident` is left null at client-creation time and is computed only when the client's first case is opened (see below).

Opening a case captures the `client_id` (which must reference an existing client), the `incident_date` (the date of injury, which must lie in the past and on or after the client's `date_of_birth`), the `incident_type` (one of the enum values `AUTO`, `SLIP_FALL`, `MEDICAL_MALPRACTICE`, `PRODUCT_LIABILITY`, `PREMISES`, or `DOG_BITE`), the `jurisdiction_state` (a two-letter uppercase code identifying where the claim will be filed), and optionally `assigned_attorney_id` and `assigned_paralegal_id` (foreign keys onto operator records — they may also be set later). On case creation, the server computes `is_minor_at_incident` on the client by asking whether the elapsed years between the client's date of birth and the case's `incident_date` is less than 18 years, and the server computes the case's `sol_deadline` via the statute-of-limitations calculation described in §3.2. A newly created case enters the `INTAKE` state with `sol_tolled_days` of 0, `gross_settlement_cents` of 0, `case_costs_cents` of 0, `filed_in_court` of false, and `disbursement_approved_by` of null.

Before any medical-records work can begin, a `ContingencyFeeAgreement` row must be recorded for the case. The agreement carries the three rate fields `pre_suit_rate_bps`, `post_suit_rate_bps`, and `trial_rate_bps` (each defaulting respectively to 3333, 4000, and 4500, each greater than 0 and at most 5000), and a `signed_at` timestamp pinned at creation time. The agreement is unique per `case_id` and immutable after creation; a second insert on the same case is rejected with `ERR_FEE_AGREEMENT_ALREADY_EXISTS`.

### 3.2. Statute of Limitations: Computation and Tolling

The statute-of-limitations cutoff is recomputed every time a case is opened and every time tolling is applied. The computation proceeds in a pinned three-step order. First, the base deadline is determined by looking up the pair `(jurisdiction_state, incident_type)` in a fixed table and adding the resulting number of base years to the `incident_date`; for example, California auto cases use 2 years, California medical-malpractice cases use 3 years, California slip-and-fall, product-liability, premises, and dog-bite cases each use 2 years, New York auto, slip-and-fall, product-liability, premises, and dog-bite cases each use 3 years, New York medical-malpractice cases use 2 years, and Texas cases of every type use 2 years. Second, if the client's `is_minor_at_incident` is true, the system computes a minor-tail deadline by adding 18 years plus a jurisdiction-specific minor tail to the client's `date_of_birth` (California's minor tail is 2 years, New York's is 3 years, and Texas's is 2 years) and replaces the base deadline with whichever of the base deadline and the minor-tail deadline is later. Third, the resulting deadline is shifted forward by `sol_tolled_days` calendar days to yield the effective `sol_deadline`. The resulting value is stored as a `YYYY-MM-DD` date string.

The hard-boundary semantic is inclusive: a case is out of statute the moment the server's current time is on or after `sol_deadline`. Tolling is applied through a `ManagingPartner` operation that supplies `additional_days` and a free-text `reason`; the system adds `additional_days` to `sol_tolled_days` and reruns the deadline calculation. Tolling is the only way `sol_tolled_days` changes.

### 3.3. Medical Records and the Path to Demand

The first medical-record request created on a case transitions the case from `INTAKE` to `RECORDS_PENDING` only if the case has a `ContingencyFeeAgreement` and the case's `sol_deadline` is more than 30 days into the future at the moment of the request — paralegals cannot start records work on a case whose statute will mature within the next month. Each request captures `provider_name` (non-empty free text), `date_of_service_start`, and `date_of_service_end`; the end date must be on or after the start date and on or after the case's `incident_date`, and a violation is rejected with `ERR_DATE_OF_SERVICE_INVALID`. A new request enters the `DRAFT` state.

Sending a request to its provider — a `Paralegal` action available only while the case is in `RECORDS_PENDING` — flips the request from `DRAFT` to `SENT` and stamps its `sent_at` to the server's current time. While a request remains in `DRAFT` it may be canceled (deleted), which moves it to `CANCELED`; once `SENT`, it cannot be deleted, only transitioned. Marking a sent request as received — accomplished by patching its `status` to `RECEIVED` together with a `billed_amount_cents` value that must be at least zero — stamps `received_at`, persists the billed amount, recomputes `Damages.medical_bills_cents` and `Damages.total_damages_cents` (bumping `Damages.version`), and, if this was the last outstanding non-terminal request and `Case.assigned_attorney_id` is set and `Damages.total_damages_cents` is now greater than zero, advances the case from `RECORDS_PENDING` to `READY_FOR_DEMAND`. If the provider declines, patching `status` to `REJECTED` records the rejection without any billed amount and may leave the case's state unchanged after the damages recomputation. A request that has reached `RECEIVED`, `REJECTED`, or `CANCELED` is terminal.

A case that is dismissed by a `ManagingPartner` while still in `INTAKE`, `RECORDS_PENDING`, or `READY_FOR_DEMAND` cascades through every open medical-record request still in `DRAFT` or `SENT` and flips each to `CANCELED`; the case itself moves to `DISMISSED`. The dismissal endpoint takes a free-text `reason` in its body. Operations against a case whose status is already `DISMISSED` or `CLOSED` are rejected with `ERR_CASE_CLOSED`.

### 3.4. Damages: The Singleton and Its Two Valuation Methods

Each case has exactly one `Damages` row, addressed under the case path. The row is created at any point after a case opens (typically once records start arriving) and is rejected with `ERR_DAMAGES_ALREADY_EXISTS` if a row already exists. Creating damages captures `lost_wages_cents` (client-attested), `property_damage_cents` (repair or replacement cost), and the non-economic valuation method `pain_suffering_method`, which is one of `MULTIPLIER` or `PER_DIEM`. When the method is `MULTIPLIER`, the payload must supply `multiplier_value` (a decimal in the closed range 1.0 to 5.0, defaulting to 1.5 and stored to one decimal place); when the method is `PER_DIEM`, the payload must supply `per_diem_rate_cents` strictly greater than zero and `per_diem_days` strictly greater than zero. A payload that omits the required inputs for its declared method, or supplies them out of range, is rejected with `ERR_DAMAGES_METHOD_INPUTS_INVALID`. Damages inputs may later be amended through a patch that accepts any of the optional fields plus the OCC `version`.

The damages total is recomputed every time the row is created or patched, every time a medical-record request transitions to `RECEIVED`, and every time the explicit recompute endpoint is invoked for the case. The computation works as follows. First, `medical_bills_cents` is set to the sum of `billed_amount_cents` over every `MedicalRecordRequest` row on the case whose `status` is `RECEIVED` (requests in `DRAFT`, `SENT`, `REJECTED`, or `CANCELED` are excluded). Second, the economic component is `medical_bills_cents` plus `lost_wages_cents` plus `property_damage_cents`. Third, `pain_suffering_cents` is computed according to the active method: under the `MULTIPLIER` method it is the economic component multiplied by `multiplier_value`, with the product rounded half-up to a whole number of cents; under the `PER_DIEM` method it is `per_diem_rate_cents` multiplied by `per_diem_days`, with no rounding because both operands are already integer values. Fourth, `total_damages_cents` is the sum of the economic component and `pain_suffering_cents`. The `MULTIPLIER` and `PER_DIEM` branches are parallel and equally specified; under the multiplier branch the multiplication of an integer cent figure by a one-decimal multiplier is the sole rounding step, and under the per-diem branch there is no rounding at all because both factors are integers.

### 3.5. Demand Letter Lifecycle and the Damages Snapshot

A demand letter is drafted by an `Attorney` against a case that is in `READY_FOR_DEMAND`. At most one active letter — one whose status is `DRAFT` or `SENT` — may exist on a case at a time; a second draft is rejected with `ERR_ACTIVE_DEMAND_EXISTS`. Drafting captures `demanded_amount_cents`, which must be greater than or equal to the current `Damages.total_damages_cents` on the linked damages row; a value below the damages total is rejected with `ERR_DEMAND_BELOW_DAMAGES`. A newly drafted letter sits in `DRAFT` with `snapshot_total_damages_cents` of 0 and `snapshot_damages_version` of 0.

Sending the letter is the action that drives the case from `READY_FOR_DEMAND` to `DEMAND_SENT`. The send operation requires the letter to be in `DRAFT` (a non-draft letter is rejected with `ERR_DEMAND_NOT_DRAFT`), the case's `sol_deadline` to still be in the future, and the demanded amount to still cover the current damages total. The caller may optionally supply `expected_damages_version` in the request body to assert which version of the damages row they intend to snapshot; if the supplied value does not match the current `Damages.version`, the send is rejected with `ERR_STALE_DAMAGES_SNAPSHOT`. On success, the letter's `sent_at` is stamped to the server's current time, its `response_due_at` is stamped at exactly 30 calendar days after `sent_at`, its `snapshot_total_damages_cents` is pinned to the current `Damages.total_damages_cents`, and its `snapshot_damages_version` is pinned to the current `Damages.version`; the letter advances to `SENT` and the case advances to `DEMAND_SENT`.

A letter that is still in `DRAFT` may be withdrawn by an `Attorney`, transitioning it to the terminal state `WITHDRAWN`. When the case enters `LITIGATION` while the letter is still in `SENT` (because a complaint is filed), the letter advances to `SUPERSEDED`. When the defense responds with its first settlement offer, the letter advances to `RESPONDED`. The states `WITHDRAWN`, `SUPERSEDED`, and `RESPONDED` are all terminal for a letter.

### 3.6. Settlement Negotiation: Offers, Counter-Offers, and Acceptance

Once a demand letter is sent, the case is open to settlement offers. Each offer carries `offer_party` (`DEFENDANT` or `PLAINTIFF`), `amount_cents` (strictly greater than zero), `expires_at` (a wall-clock instant), and optionally `predecessor_offer_id`. The first offer registered on a case omits `predecessor_offer_id` and is round 1; the server computes `round_number` as the length of the chain of predecessors plus one. A counter-offer must reference an existing predecessor offer on the same case via `predecessor_offer_id` and the new offer's `offer_party` must be the opposite of the predecessor's; a counter where the predecessor lives on a different case, or where the party is the same as the predecessor's, is rejected with `ERR_OFFER_PARTY_INVALID`. The predecessor offer must still be `PENDING` and unexpired; otherwise the counter is rejected with `ERR_OFFER_NOT_PENDING`. Recording a counter automatically flips the predecessor offer from `PENDING` to `COUNTERED`.

The first defendant-party offer registered against a case in `DEMAND_SENT` cascades the demand letter from `SENT` to `RESPONDED` and the case from `DEMAND_SENT` to `NEGOTIATING`. Subsequent offers on the same case while it is in `NEGOTIATING` remain in `NEGOTIATING` and simply lengthen the chain, producing the cyclic round-1, round-2, round-3 negotiation pattern. An offer's lifecycle states are `PENDING`, `ACCEPTED`, `REJECTED`, `COUNTERED`, `EXPIRED`, and `WITHDRAWN`; the four states `ACCEPTED`, `REJECTED`, `EXPIRED`, and `WITHDRAWN` are terminal.

Accepting an offer is an `Attorney` action and is only permitted while the case is in `NEGOTIATING` or `LITIGATION` (a case in any other state is rejected with `ERR_CASE_INVALID_STATE`), and only while the offer itself is still `PENDING` and its `expires_at` is still in the future. Acceptance cascades through four hops in order: the accepted offer transitions from `PENDING` to `ACCEPTED`; `Case.gross_settlement_cents` is set equal to the accepted offer's `amount_cents`; every other offer on the same case that is still in `PENDING` is flipped to `WITHDRAWN`; and the case advances to `SETTLED`. Acceptance after the case has already entered `LITIGATION` follows the same four-hop cascade, but the contingency tier that will later apply at disbursement is the post-suit tier rather than the pre-suit tier. Rejecting an offer requires the offer to be `PENDING` and unexpired and simply flips its state to `REJECTED` with no cascade.

A daily sweep against the offer table examines every offer whose status is `PENDING` and whose `expires_at` is in the past, flipping each to `EXPIRED`. The sweep is callable only by a `ManagingPartner` and operates against the server's logical clock — administrative test-driving exposes both a clock-advance capability that moves the logical clock forward by a supplied number of `seconds` and a read-only clock-now capability. A pending offer may also be flipped to `WITHDRAWN` as a side-effect cascade when the case enters `LITIGATION` or when a sibling offer on the same case is accepted.

### 3.7. Court Calendar, Filing, Trial, and Award

Court events are scheduled by either an `Attorney` or a `Paralegal`. Each event carries `event_type` (one of `COMPLAINT_FILED`, `ANSWER_DUE`, `DISCOVERY_DEADLINE`, `MEDIATION`, `MOTION_HEARING`, `TRIAL`, or `JUDGMENT`), `scheduled_at` (a wall-clock instant), `duration_minutes` (an integer between 15 and 480 inclusive, used for calendar-conflict math), and optionally `courtroom` (a free-text identifier, or null). The scheduled time must be strictly after the case's `incident_date` and strictly before the case's `sol_deadline` plus five years (a sanity bound on stale calendaring); violations are rejected with `ERR_COURT_EVENT_TIME_INVALID`. New events start in `SCHEDULED`.

Two calendar-conflict checks guard event creation. The attorney calendar check looks at every other event scheduled on a case whose `assigned_attorney_id` matches the current case's assigned attorney, considering only events whose status is `SCHEDULED` or `CONTINUED` (events in `COMPLETED` or `CANCELED` do not count). Each event's time window is treated as a half-open interval beginning at `scheduled_at` and ending `duration_minutes` later, with a 15-minute travel buffer added to each side. Two events conflict if and only if the later of the two buffered start times is strictly less than the earlier of the two buffered end times — equivalently, two events conflict if and only if their buffered half-open intervals overlap with positive overlap. Adjacency exactly at the buffered edge (the back-to-back case where one event's buffered end equals the next event's buffered start, producing a 30-minute clearance between the unbuffered windows) does not conflict and is allowed. A conflict is rejected with `ERR_ATTORNEY_CALENDAR_CONFLICT`. The courtroom check is narrower: any two events that share the same non-null `courtroom` string conflict if and only if their unbuffered half-open intervals (`scheduled_at` through `scheduled_at` plus `duration_minutes`) overlap, with no buffer; touching boundaries (one event's end equal to the next event's start) do not conflict. A courtroom conflict is rejected with `ERR_COURTROOM_DOUBLE_BOOKED`.

The first event with `event_type` equal to `COMPLAINT_FILED` created on a case is the case's entry into litigation. If the case is in `DEMAND_SENT` with no defendant offer received and the demand letter's `response_due_at` has already passed, that filing cascades the demand letter from `SENT` to `SUPERSEDED`, flips `Case.filed_in_court` to true, and advances the case from `DEMAND_SENT` to `LITIGATION`. If the case is in `NEGOTIATING` with at least one offer of any round on file and the `sol_deadline` is still in the future, filing the complaint cascades every offer still in `PENDING` to `WITHDRAWN`, flips `Case.filed_in_court` to true, and advances the case from `NEGOTIATING` to `LITIGATION`. Once `Case.filed_in_court` is true, the contingency tier used by the attorney-fee calculation flips from pre-suit to post-suit (see §3.9).

A scheduled event may be marked `COMPLETED` by an `Attorney` once the server's current time has reached or passed the event's `scheduled_at`. If the completed event's `event_type` is `JUDGMENT` and the patch body supplies an `award_amount_cents` strictly greater than zero, the case advances from `LITIGATION` to `TRIAL_AWARDED`, `Case.gross_settlement_cents` is set equal to `award_amount_cents`, and the contingency tier used by attorney-fee calculation becomes the trial tier. A scheduled event may also be marked `CONTINUED` with a new `scheduled_at` that is strictly later than the previous `scheduled_at`. A scheduled event may be canceled (deleted), moving it to `CANCELED`.

### 3.8. Liens: Recording, Negotiation, Dispute, and Priority

Each case may carry any number of liens against the settlement proceeds. A lien is recorded with `lienholder_name`, `lien_type` (one of `MEDICARE`, `MEDICAID`, `ERISA`, `HOSPITAL_STATUTORY`, `PROVIDER_NEGOTIATED`, `CHILD_SUPPORT`, or `ATTORNEY_PRIOR_COUNSEL`), and `face_amount_cents` (strictly greater than zero). A newly recorded lien enters `ASSERTED` with `negotiated_amount_cents` null, `final_paid_amount_cents` null, and `priority_rank` null.

Liens of type `PROVIDER_NEGOTIATED`, `HOSPITAL_STATUTORY`, or `ATTORNEY_PRIOR_COUNSEL` are negotiable: a `Paralegal` opens negotiation by invoking the negotiate action against the lien, which moves it from `ASSERTED` to `NEGOTIATING`. A subsequent patch supplying `negotiated_amount_cents` (which must be strictly greater than zero and at most `face_amount_cents`; otherwise `ERR_LIEN_NEGOTIATION_INVALID`) moves the lien from `NEGOTIATING` to `REDUCED`. Liens of type `MEDICARE`, `MEDICAID`, `ERISA`, or `CHILD_SUPPORT` are statutory and are not opened to negotiation by the paralegal; instead, they remain in `ASSERTED` and are auto-reduced by the disbursement cascade according to a formula (see §3.10), at which point they move from `ASSERTED` to `REDUCED` as a system-driven transition. Any lien — statutory or negotiable — may be disputed by an `Attorney`, moving it directly from `ASSERTED` to `DISPUTED`; a disputed lien is excluded from disbursement payment but is still recorded.

The disbursement waterfall (§3.10) is the only place where `final_paid_amount_cents` and `priority_rank` are set. Once `final_paid_amount_cents` is set and the lien is paid, it advances to `RESOLVED`; `RESOLVED` and `DISPUTED` are the lien's terminal states.

### 3.9. Case Costs and the Contingency Tier

The firm's advanced case costs are tracked on `Case.case_costs_cents` and accumulated by a patch endpoint accepting a new `case_costs_cents` value (and an optional `version` for OCC). Case costs are append-only: a patch whose new value is strictly less than the stored value is rejected with `ERR_COSTS_DECREASE_NOT_ALLOWED`; a patch whose new value is greater than or equal to the stored value updates the row and bumps its version. The intent is that filing fees, expert-witness payments, and other case expenses are added as they are incurred but cannot be retroactively reduced or zeroed.

The contingency tier in force on a case at the moment of disbursement is determined by case state in pinned order. If `Case.status` is `TRIAL_AWARDED`, the trial rate `trial_rate_bps` applies. Otherwise, if `Case.filed_in_court` is true, the post-suit rate `post_suit_rate_bps` applies — this is the path taken when the case settles after a complaint has been filed. Otherwise, the pre-suit rate `pre_suit_rate_bps` applies — this is the path taken when the case settles before any complaint is filed. The attorney fee in cents is the gross settlement multiplied by the chosen rate divided by ten thousand, with the product rounded half-up to a whole number of cents.

### 3.10. Disbursement: Approval, Segregation, and the Waterfall

Disbursement is the final hop of every case that resolved with money. It is approved by a `ManagingPartner` against a case whose status is `SETTLED` or `TRIAL_AWARDED`. The approval call carries `strategy` in its body, naming one of `CHRONOLOGICAL_PRIORITY` or `FORWARD_LOOKING_PRORATA`. Three guard rails fire before any money math runs. First, `Case.disbursement_approved_by` must still be null — a second approval on a case that has already been approved is rejected with `ERR_DISBURSEMENT_ALREADY_APPROVED`. Second, the acting user's `X-User-ID` must not equal `Case.assigned_attorney_id` — the same person cannot have negotiated the settlement and approved the payout, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Third, every lien on the case must already be in a state acceptable for disbursement: any lien whose status is `NEGOTIATING` blocks the approval (it must first complete to `REDUCED` or be moved to `DISPUTED`); statutory liens of type `MEDICARE`, `MEDICAID`, `ERISA`, or `CHILD_SUPPORT` may remain in `ASSERTED` because the disbursement cascade auto-reduces them via the statutory formula; non-statutory liens of type `HOSPITAL_STATUTORY`, `ATTORNEY_PRIOR_COUNSEL`, or `PROVIDER_NEGOTIATED` must be in `REDUCED`, `RESOLVED`, or `DISPUTED`.

When the guards pass, the waterfall executes the following sequence. First, the attorney fee is computed using `calc_attorney_fee` against the active contingency tier, yielding `attorney_fee_cents`. Second, the system computes a running pool: net-after-fee is `gross_settlement_cents` minus `attorney_fee_cents`, and the lien pool is net-after-fee minus the snapshotted `case_costs_cents`. Third, every lien is ordered for payment. The priority order by `lien_type` is `MEDICARE` first, then `MEDICAID`, then `ERISA`, then `CHILD_SUPPORT`, then `HOSPITAL_STATUTORY`, then `ATTORNEY_PRIOR_COUNSEL`, then `PROVIDER_NEGOTIATED`. Within a single `lien_type` bucket, liens are tie-broken by ascending `created_at` and then by ascending `id`. The `priority_rank` on each lien row is set to the resulting one-indexed position.

Fourth, the per-lien payment depends on `strategy`. Under `CHRONOLOGICAL_PRIORITY`, liens are paid in the ordered pass in strict priority order. For each lien in that order: if the lien's `lien_type` is `MEDICARE`, `MEDICAID`, `ERISA`, or `CHILD_SUPPORT` and `negotiated_amount_cents` is null, the system applies the statutory ratable-reduction formula — the attorney ratio is `attorney_fee_cents` divided by `gross_settlement_cents` and the cost ratio is `case_costs_cents` divided by `gross_settlement_cents`, and the reduced figure for the lien is `face_amount_cents` multiplied by the quantity one minus the attorney ratio minus the cost ratio, with the product rounded half-up to a whole number of cents; the actual payment for that lien is the smaller of the reduced figure and the remaining pool, and that lien's `status` moves from `ASSERTED` to `REDUCED` as part of the cascade. Otherwise, the payment for that lien is the smaller of (a) `negotiated_amount_cents` if it is non-null, or `face_amount_cents` if it is null, and (b) the remaining pool. The lien's `final_paid_amount_cents` is set to that payment, and the payment is subtracted from the remaining pool. Liens whose status is `DISPUTED` are skipped entirely: their `final_paid_amount_cents` is set to zero and their status remains `DISPUTED`. After every lien is processed, `client_net_cents` equals whatever remains in the pool.

Under `FORWARD_LOOKING_PRORATA`, the system first sums the `face_amount_cents` across every lien on the case (call this the face sum). Then, in the same priority-rank order with the same tie-break, each lien is assigned a pro-rata share equal to its `face_amount_cents` multiplied by the smaller of (the lien pool, the face sum), divided by the face sum, with the product rounded half-up to a whole number of cents. The actual payment is the smaller of the pro-rata share and the remaining pool, the lien's `final_paid_amount_cents` is set to that payment, and the payment is subtracted from the remaining pool. After the ordered pass, any cents that remain in the pool because of per-lien rounding residue are added back to the last lien in the ordered pass (this is the pinned residual-rounding rule). Disputed liens are skipped under the pro-rata strategy in exactly the same way as under the chronological strategy. The final `client_net_cents` under pro-rata is the larger of zero and the lien pool minus the sum of all `final_paid_amount_cents` that were paid out.

A new `SettlementDisbursement` row is created at the end of the cascade. It carries `gross_amount_cents` copied from `Case.gross_settlement_cents` at the time of approval, the computed `attorney_fee_cents`, `case_costs_cents` snapshotted from the case at approval time, `total_lien_payment_cents` summed across the just-finalized lien payments on the case, `client_net_cents` from the waterfall, the `strategy` that was requested, and `approved_by` copied from the calling `X-User-ID`. The system also writes `disbursement_approved_by` onto the case, copies it from the approver, and finally flips `Case.status` to `CLOSED`. The post-condition `gross_amount_cents` minus `attorney_fee_cents` minus `case_costs_cents` minus `total_lien_payment_cents` must equal `client_net_cents` with no cents drift; if the computation drifts or `client_net_cents` would be negative, the approval is rejected with `ERR_NET_BELOW_ZERO`. Both disbursement variants — `CHRONOLOGICAL_PRIORITY` and `FORWARD_LOOKING_PRORATA` — share the same priority ordering and tie-break and the same lien-status preconditions; they differ only in the per-lien payment formula and (in the pro-rata case) the residual-rounding rule that hands the final cents to the last lien.

## 4. Endpoint Definitions

A successful resource creation returns HTTP 201 with the created resource in `data`. A successful modification, fetch, action, or list returns HTTP 200 with the affected or retrieved resource in `data`. Deletions return HTTP 204 with no body. Endpoint descriptions below are minimal; the complete request body, response body, side effects, and validation conditions for any endpoint must be reconstructed from §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /clients | Create a client (intake step 1). | Paralegal, Attorney, ManagingPartner |
| GET | /clients/{cid} | Fetch a client. | Paralegal, Attorney, ManagingPartner |
| POST | /pi-cases | Open a new case. | Paralegal, Attorney, ManagingPartner |
| GET | /pi-cases/{id} | Fetch a case. | Paralegal, Attorney, ManagingPartner |
| GET | /pi-cases | List cases with filters. | Paralegal, Attorney, ManagingPartner |
| PATCH | /pi-cases/{id}/costs | Increment case_costs_cents (append-only). | Attorney, ManagingPartner |
| POST | /pi-cases/{id}/toll | Apply tolling days to the SoL deadline. | Attorney, ManagingPartner |
| POST | /pi-cases/{id}/dismiss | Dismiss a case before settlement. | ManagingPartner |
| POST | /pi-cases/{id}/disbursement/approve | Approve final disbursement on a SETTLED or TRIAL_AWARDED case. | ManagingPartner |
| POST | /pi-cases/{cid}/contingency-fee | Record the signed contingency fee agreement (immutable). | ManagingPartner, Attorney |
| GET | /pi-cases/{cid}/contingency-fee | Fetch the fee agreement. | Paralegal, Attorney, ManagingPartner |
| POST | /pi-cases/{cid}/medical-record-requests | Create a draft medical-record request. | Paralegal, Attorney |
| POST | /pi-cases/{cid}/medical-record-requests/{rid}/send | Send request to provider. | Paralegal, Attorney |
| PATCH | /pi-cases/{cid}/medical-record-requests/{rid} | Update status to RECEIVED or REJECTED. | Paralegal, Attorney |
| GET | /pi-cases/{cid}/medical-record-requests | List medical-record requests on a case. | Paralegal, Attorney, ManagingPartner |
| DELETE | /pi-cases/{cid}/medical-record-requests/{rid} | Cancel a draft request. | Paralegal, Attorney |
| POST | /pi-cases/{cid}/damages | Create the singleton Damages row. | Paralegal, Attorney |
| PATCH | /pi-cases/{cid}/damages | Update damages inputs. | Paralegal, Attorney |
| GET | /pi-cases/{cid}/damages | Fetch damages. | Paralegal, Attorney, ManagingPartner |
| POST | /pi-cases/{cid}/damages/recompute | Force recomputation of medical_bills_cents and total. | Paralegal, Attorney |
| POST | /pi-cases/{cid}/liens | Record an asserted lien. | Paralegal, Attorney |
| POST | /pi-cases/{cid}/liens/{lid}/negotiate | Open negotiation on a lien. | Paralegal, Attorney |
| PATCH | /pi-cases/{cid}/liens/{lid} | Set negotiated amount or dispute outcome. | Paralegal, Attorney |
| POST | /pi-cases/{cid}/liens/{lid}/dispute | Mark lien as DISPUTED. | Attorney |
| GET | /pi-cases/{cid}/liens | List liens on case. | Paralegal, Attorney, ManagingPartner |
| POST | /pi-cases/{cid}/demand-letters | Draft a demand letter. | Attorney |
| POST | /pi-cases/{cid}/demand-letters/{lid}/send | Send the letter; snapshots Damages. | Attorney |
| POST | /pi-cases/{cid}/demand-letters/{lid}/withdraw | Withdraw a DRAFT demand letter. | Attorney |
| POST | /pi-cases/{cid}/settlement-offers | Record a new offer (round 1 or counter). | Attorney |
| PATCH | /pi-cases/{cid}/settlement-offers/{oid} | Accept or reject an offer. | Attorney |
| GET | /pi-cases/{cid}/settlement-offers | List offers on case, ordered by round_number then created_at. | Paralegal, Attorney, ManagingPartner |
| POST | /pi-cases/{cid}/court-events | Create a court calendar entry. | Attorney, Paralegal |
| PATCH | /pi-cases/{cid}/court-events/{eid} | Mark event COMPLETED or CONTINUED, or attach JUDGMENT award. | Attorney |
| DELETE | /pi-cases/{cid}/court-events/{eid} | Cancel a scheduled event. | Attorney |
| GET | /pi-cases/{cid}/court-events | List court events. | Paralegal, Attorney, ManagingPartner |
| POST | /_clock/advance | Advance the server's logical clock by N seconds (test harness). | ManagingPartner |
| GET | /_clock/now | Read current server time. | Paralegal, Attorney, ManagingPartner |
| POST | /_sweep/settlement_offers | Run the daily PENDING-offer expiry sweep. | ManagingPartner |
| POST | /_sweep/sol | Run the SoL-expiry sweep. | ManagingPartner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_AUTH_HEADERS | 401 |
| ERR_UNKNOWN_ROLE | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_CASE_CLOSED | 409 |
| ERR_CASE_INVALID_STATE | 409 |
| ERR_DEMAND_NOT_DRAFT | 409 |
| ERR_OFFER_NOT_PENDING | 409 |
| ERR_DAMAGES_ALREADY_EXISTS | 409 |
| ERR_FEE_AGREEMENT_ALREADY_EXISTS | 409 |
| ERR_ACTIVE_DEMAND_EXISTS | 409 |
| ERR_STALE_DAMAGES_SNAPSHOT | 409 |
| ERR_DISBURSEMENT_ALREADY_APPROVED | 409 |
| ERR_VERSION_MISMATCH | 409 |
| ERR_ATTORNEY_CALENDAR_CONFLICT | 409 |
| ERR_COURTROOM_DOUBLE_BOOKED | 409 |
| ERR_STATUTE_OF_LIMITATIONS_EXPIRED | 422 |
| ERR_DATE_OF_SERVICE_INVALID | 422 |
| ERR_OFFER_PARTY_INVALID | 422 |
| ERR_LIEN_NEGOTIATION_INVALID | 422 |
| ERR_DEMAND_BELOW_DAMAGES | 422 |
| ERR_DAMAGES_METHOD_INPUTS_INVALID | 422 |
| ERR_COURT_EVENT_TIME_INVALID | 422 |
| ERR_NET_BELOW_ZERO | 422 |
| ERR_COSTS_DECREASE_NOT_ALLOWED | 422 |
