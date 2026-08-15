# Consumer Protection Mediation API — Product Requirements Document

## 1. Introduction

A state attorney general's consumer unit sits between two publics: consumers who believe a business has wronged them, and businesses entitled to due process before their names appear in a government record. This document specifies the Consumer Protection Mediation API, the system of record through which a complaint travels from initial filing, through jurisdiction screening and business response, into voluntary mediation, settlement, and restitution — and, where the evidence warrants, onward to the enforcement division.

The unit's authority is deliberately bounded. It mediates; it does not adjudicate. Cases it cannot resolve are closed with guidance toward alternative forums, and businesses whose closed cases reveal a pattern of harm are escalated to enforcement attorneys who operate under a strict separation from the mediation staff. Because every case outcome feeds a published complaint record and a public business rating, the system treats timing — filing windows, response deadlines, offer expiry, cooling-off periods, publication embargoes — as a first-class concern, driven by a controllable logical clock rather than the wall clock, and it treats segregation of duties as a compliance requirement rather than a courtesy.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which that party acts. The system recognizes seven roles: `Anonymous`, `Consumer`, `Business`, `IntakeOfficer`, `Mediator`, `EnforcementAttorney`, and `UnitDirector`. A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the role is recognized but does not appear among the roles authorized for the target operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Three roles are entity-backed. When `X-User-Role` is `Consumer`, `X-User-ID` is the `id` of the acting `Consumer` record; ownership checks on any resource that references a consumer compare the resource's `consumer_id` to `X-User-ID`. When `X-User-Role` is `Business`, `X-User-ID` is the `id` of the acting `Business` record, and ownership checks compare `business_id` fields to it. When `X-User-Role` is `Mediator`, `X-User-ID` is the `id` of the acting `Mediator` record, and session ownership compares the session's `mediator_id` to it. An entity-backed caller acting outside its own scope — a consumer touching another consumer's complaint, a business answering a complaint filed against someone else, a mediator completing a colleague's session — is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The remaining four roles carry opaque identifiers. When `X-User-Role` is `Anonymous`, `IntakeOfficer`, `EnforcementAttorney`, or `UnitDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `accepted_by_officer_id` or `closed_by_officer_id` on a complaint, as `referred_by_user_id` or `reviewed_by_user_id` on an enforcement referral, or as `drafted_by_user_id` on a scam alert — but it never compares that identifier to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, and any value below 1 or above 100 is out of range. The `offset` parameter controls how many items are skipped and defaults to 0. Unless otherwise specified, every list is returned in creation order — `created_at` ascending.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Resource Identity, Common Fields, and the Case Event Trail

Every resource in the system carries a server-minted `id` formatted as a bare UUID, with no type prefix. Alongside it, every resource except the audit-trail entry carries `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and an integer `version` that increments with every mutation of the resource; `updated_at` refreshes on the same occasions. Derived-field recomputations and state transitions count as mutations like any other.

The audit trail is the one exception. A `ComplaintEvent` carries only `id` and `created_at`; both `updated_at` and `version` are absent, because the trail is append-only and individual entries — retrievable by `eventId` — never change after they are written. Each entry records the `complaint_id` it belongs to, an `event_type`, the `from_status` and `to_status` of the underlying transition (both null for events that are not status transitions), the `actor_role` and `actor_id` taken from the acting request's headers (or the literal value `system` for clock sweeps), and a machine-generated `note` holding detail such as an allocation breakdown. The event vocabulary is fixed: `CREATED`, `STATE_CHANGED`, `RESPONSE_FILED`, `RESPONSE_REVIEWED`, `SESSION_SCHEDULED`, `SESSION_CONFIRMED`, `SESSION_COMPLETED`, `OFFER_TENDERED`, `OFFER_ACCEPTED`, `OFFER_RESCINDED`, `SETTLEMENT_CREATED`, `SETTLEMENT_EXECUTED`, `SETTLEMENT_BREACHED`, `PAYMENT_ALLOCATED`, `PAYMENT_RETURNED`, `PAYMENT_DISBURSED`, `REFERRAL_FILED`, `REFERRAL_RETURNED`, `CASE_CLOSED`, `PUBLISHED`, and `REDACTED`. The trail is queryable per complaint through an optional `complaint_id` filter.

### 2.5. Resource Addressing and Existence

Identifiers in a request path are validated sequentially from left to right, and the first identifier that fails to resolve determines the error returned. A `{consumerId}` that matches nothing yields `ERR_CONSUMER_NOT_FOUND`; an unresolvable `{businessId}` yields `ERR_BUSINESS_NOT_FOUND`; the same pattern gives `ERR_COMPLAINT_NOT_FOUND` for `{complaintId}`, `ERR_MEDIATOR_NOT_FOUND` for `{mediatorId}`, `ERR_ROOM_NOT_FOUND` for `{roomId}`, `ERR_RESPONSE_NOT_FOUND` for `{responseId}`, `ERR_SESSION_NOT_FOUND` for `{sessionId}`, `ERR_OFFER_NOT_FOUND` for `{offerId}`, `ERR_SETTLEMENT_NOT_FOUND` for `{settlementId}`, `ERR_PAYMENT_NOT_FOUND` for `{paymentId}`, `ERR_REFERRAL_NOT_FOUND` for `{referralId}`, and `ERR_ALERT_NOT_FOUND` for `{alertId}` — all HTTP 404. Foreign keys carried in request bodies must resolve as well, drawing from the same error family.

### 2.6. The Logical Clock and Scheduled Sweeps

All temporal reasoning in the system runs on a logical clock, never the wall clock. At startup the logical clock reads exactly 2026-08-01T00:00:00Z. A `UnitDirector`-only capability advances it to a supplied `to_iso8601` instant and reports the resulting `current_utc`; every deadline, expiry, embargo, and window in this document is measured against that logical time.

Each clock set performs an ordered sweep before responding. First, complaints still in `BUSINESS_NOTIFIED` whose `response_deadline` has strictly passed flip to `RESPONSE_OVERDUE`. Second, settlement offers still `TENDERED` whose `expires_at` has strictly passed become `EXPIRED`. Third, complaints sitting in `EMBARGOED` whose embargo has matured — current time at or after `closed_at` plus ten days — become `PUBLISHED`, with the business's published count and rating recomputed as described in §3.9. Complaints are processed in filing order: earlier `filed_at` first, ties broken by ascending `filing_seq`. Every transition the sweep performs writes its own entry to the case event trail.

### 2.7. Segregation of Duties

Three duty pairs are enforced across the unit, each refusing the request with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422) when the same operator appears on both sides. The intake officer who accepted a complaint may not be the one who closes it unresolved. The staff member who referred a case to enforcement may not review that referral. And the drafter of a scam alert may not publish it. These checks compare the caller's `X-User-ID` against the identifier recorded at the earlier act; they are identity comparisons between operators, not entity lookups.

### 2.8. Optimistic Concurrency Control on Negotiation Writes

Exactly two writes carry an optimistic-concurrency token: tendering a settlement offer on a complaint, and documenting a settlement on a complaint. Each request must include `expected_complaint_version`, a non-optional field carrying the complaint `version` the client last observed. If the complaint's current `version` has advanced beyond the supplied value, the write is refused with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the complaint before retrying.

The guard exists because both writes legitimately rewrite shared negotiation state: tendering an offer supersedes the complaint's currently open offer and advances the complaint's `version` by one, and documenting a settlement supersedes an existing settlement and likewise advances the `version`. A client holding a stale view would otherwise overwrite negotiation state it never observed. Endpoints other than these two accept no version field.

### 2.9. Monetary Values and Rounding Discipline

All money in the system is integer cents. Amounts are never represented as fractional currency. Where a computation produces a fraction, the result is rounded half-up to whole cents, and each computation has exactly one pinned rounding point so results cannot drift with implementation choices: the mediation fee rounds at the fee step only; the pattern score rounds once after the size multiplier is applied; the rolling rating rounds its weighted demerit sum before that sum is subtracted from 100; pro-rata allocation rounds each obligation's share before any cent-by-cent reconciliation; and the published-case statistics round their average to whole days. Timestamps compared against deadlines use second precision, and the filing window is measured in whole calendar days.

### 2.10. Two Independent Axes: Case Progress and Publication

A complaint lives on two independent state axes. The case axis, `case_status`, tracks the work itself: `RECEIVED`, `ACCEPTED`, `BUSINESS_NOTIFIED`, `RESPONSE_RECEIVED`, `RESPONSE_OVERDUE`, `MEDIATION_OFFERED`, `MEDIATION_ACTIVE`, `MEDIATION_IMPASSE`, `SETTLEMENT_PENDING`, and the terminal outcomes `SETTLED`, `CLOSED_UNRESOLVED`, `REFERRED_ENFORCEMENT`, and `DECLINED`. The publication axis, `publication_status`, tracks public visibility: `UNPUBLISHED`, `EMBARGOED`, `PUBLISHED`, `SUPPRESSED`, and `REDACTED`.

The axes move together only at closure. When a case reaches `SETTLED`, `CLOSED_UNRESOLVED`, or `REFERRED_ENFORCEMENT`, a complaint filed with `publication_consent` moves from `UNPUBLISHED` to `EMBARGOED` — a ten-day quiet period measured from `closed_at`, after which the clock sweep publishes it — while one filed without consent moves to `SUPPRESSED` and never surfaces. A declined complaint simply stays `UNPUBLISHED` forever. Once published, a complaint can still leave the record: the consumer may retract it, moving it to `REDACTED`. And when enforcement sends a referred case back to mediation, an embargo that never matured rolls back to `UNPUBLISHED`.

### 2.11. Derived Business Signals: Watch Bands and the Public Rating

Two computed signals ride on every business. The `pattern_score` is a rolling, severity-weighted count of the business's terminal complaints, maintained for the unit's own surveillance; the bands derived from it gate the mediation track. A business scoring below 60 sits `CLEAR`. A score of at least 60 and below 100 places it on the `WATCHLIST`. A score of 100 or more — the boundary is inclusive — marks it `FLAGGED`, and while that band holds, no complaint against the business may be offered mediation at all: the attempt is refused with `ERR_PATTERN_REFERRAL_REQUIRED`, because a pattern violator belongs with enforcement until its score falls back below the band.

The public face is the rating: a `rating_score` that starts at 100 and sheds demerits for published complaints, banded into `rating_tier` letters `A`, `B`, `C`, and `D`. Both signals are recomputed at well-defined moments — terminal closures and referral returns for the watch score; publications, retractions, and rating-method switches for the rating — and the exact formulas appear in §3.8 and §3.9 respectively.

### 2.12. Order of Validation

Checks on any request run in a fixed order, and a failure at an earlier step masks every later one — a request that fails authentication never reveals whether its payload was malformed.

1. Authentication: the headers are present and the role is recognized, else `ERR_UNAUTHENTICATED`.
2. Authorization: the role is permitted on this endpoint, else `ERR_FORBIDDEN`.
3. Ownership: entity-backed callers stay inside their own scope, else `ERR_NOT_RESOURCE_OWNER`.
4. Existence: path identifiers resolve left to right, and foreign keys in the body resolve, else the appropriate not-found error of §2.5.
5. Request shape: required fields are present, types and enum members are valid, and amount rules hold — a payment's `amount_cents` must be strictly positive, an offer's `restitution_amount_cents` may be zero but never negative, and a session's `ends_at` must fall strictly after its `starts_at` — else `ERR_INVALID_REQUEST` or `ERR_INVALID_AMOUNT`.
6. State: the target entity sits in a valid from-state for the requested transition, else `ERR_INVALID_STATE`.
7. Regulatory gates: the filing window at complaint creation, jurisdiction at screening, the segregation-of-duties pairs, the `FLAGGED` bar on mediation offers, and mediator conflict-of-interest screening, else `ERR_FILING_WINDOW_EXPIRED`, `ERR_NO_JURISDICTION`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_PATTERN_REFERRAL_REQUIRED`, or `ERR_MEDIATOR_CONFLICT_OF_INTEREST`.
8. Uniqueness and capacity: duplicate-complaint detection, registration uniqueness, the stale-version guard, mediator and room calendar conflicts, the caseload cap, duplicate active alerts, the resubmission cap, and the single-use appeal, else `ERR_DUPLICATE_COMPLAINT`, `ERR_UNIQUENESS_VIOLATION`, `ERR_STALE_VERSION`, `ERR_MEDIATOR_TIME_CONFLICT`, `ERR_ROOM_TIME_CONFLICT`, `ERR_MEDIATOR_CASELOAD_FULL`, `ERR_DUPLICATE_ACTIVE_ALERT`, `ERR_RESUBMISSION_CAP_REACHED`, or `ERR_APPEAL_ALREADY_USED`.
9. Referenced configuration: a session may name only an `ACTIVE` mediator and an `OPERATIONAL` room, else `ERR_REFERENCED_ENTITY_INACTIVE`.
10. Clock rules: sessions must start in the future, settlement execution must wait out the cooling-off, rescission must beat the cooling-off deadline, and breach must wait until the due date has passed, else `ERR_SESSION_IN_PAST`, `ERR_COOLING_OFF_ACTIVE`, `ERR_RESCISSION_WINDOW_EXPIRED`, or `ERR_BREACH_NOT_DUE`.
11. The fiscal gate: a payment being marked received may not exceed the business's total open outstanding, else `ERR_RESTITUTION_EXCEEDS_OUTSTANDING`.

## 3. Business Logic & Workflows

### 3.1. Registration and the Public Directory

Anyone may register as a consumer. Self-service registration takes a `full_name`, an `email`, a two-letter `state_code` of residence, and an optional `phone`. Email addresses are unique across consumers, and a duplicate is refused with `ERR_UNIQUENESS_VIOLATION`.

Business registration is likewise open to the public. It records the `legal_name`, the `home_state` of incorporation, the `operates_in_states` list — two-letter codes for every state where the business transacts, which later drives jurisdiction screening — the industry `naics_code`, and optionally a `dba_name`, a `size_tier`, and a `rating_method`. The size tier is `SMALL` unless the registrant declares `MEDIUM` or `LARGE`, and the rating method is `LIFETIME` unless `ROLLING_12M` is chosen. The combination of `legal_name` and `home_state` is unique; a duplicate draws `ERR_UNIQUENESS_VIOLATION`. A freshly registered business starts with a `watch_status` of `CLEAR`, a `pattern_score` of 0, a `rating_score` of 100 in tier `A`, a `published_complaint_count` of 0, an `overdue_response_count` of 0, and a `next_filing_seq` of 1.

The business directory — list and detail — is open to the public, and so are the computed rating and statistics views described in §3.9. A `UnitDirector` may later switch a business's `rating_method` between its two variants; the switch recomputes `rating_score` and `rating_tier` under the new variant within the same request, so the response already reflects the new method.

Staffing the mediation roster is a `UnitDirector` responsibility. Registering a mediator takes a `full_name`, an `employee_ref` that must be unique (collisions draw `ERR_UNIQUENESS_VIOLATION`), an optional `max_concurrent_cases` caseload cap that defaults to 10, and an optional `conflicted_business_ids` list naming businesses the mediator must never be assigned to. New mediators enter the roster with a `mediator_status` of `ACTIVE`. Deactivation moves `mediator_status` to `INACTIVE`: sessions already on their calendar are untouched, but any attempt to schedule them anew is rejected with `ERR_REFERENCED_ENTITY_INACTIVE`. Mediation rooms are registered with a unique `room_name`, a `capacity`, and a `location`, and begin with a `room_status` of `OPERATIONAL`; taking a room out of service moves `room_status` to `OUT_OF_SERVICE` and blocks new bookings the same way.

### 3.2. Filing a Complaint: Intake, Jurisdiction, and the Filing Window

A `Consumer` files a complaint by naming the `consumer_id` — which must be the caller's own identifier — the respondent `business_id`, the `incident_date` as a calendar date in `YYYY-MM-DD` form, the two-letter `incident_state` where the transaction occurred, a `category`, a free-text `description`, and the claimed loss `amount_in_dispute_cents`. Categories are `DECEPTIVE_PRACTICE`, `REFUND_REFUSAL`, `DEFECTIVE_PRODUCT`, `BILLING_DISPUTE`, `WARRANTY_DENIED`, `CONTRACT_VIOLATION`, and `OTHER`. The claimed amount may be zero but never negative, and the filer may withhold `publication_consent` — consent is the default when the field is omitted.

Timeliness is measured in whole days between the `incident_date` and the filing date stamped into `filed_at` by the logical clock. A complaint filed at most 365 days after the incident is eligible, and an elapsed span of exactly 365 days still qualifies; at 366 days the filing is refused with `ERR_FILING_WINDOW_EXPIRED`. Nor will the unit work the same grievance twice: a new complaint matching an existing complaint's `consumer_id`, `business_id`, `incident_date`, and `category` is refused with `ERR_DUPLICATE_COMPLAINT` — unless the earlier complaint sits in `DECLINED`, in which case it no longer blocks refiling.

On acceptance of the filing, the complaint draws the business's next filing sequence number: `filing_seq` is copied from the business's `next_filing_seq`, which then advances by one, giving every business a gapless filing order that later drives restitution allocation and the clock sweep's processing order. The complaint is stamped with `filed_at`, opens with a `case_status` of `RECEIVED` and a `publication_status` of `UNPUBLISHED`, and records its jurisdiction worksheet in `jurisdiction_factors` — three booleans evaluated at creation: `incident_in_state` (the `incident_state` is Oregon, code `OR`), `business_operates_in_state` (Oregon appears in the business's `operates_in_states`), and `within_filing_window`. A `CREATED` event opens the case's audit trail, and `appeal_used`, `response_attempts`, and `ever_response_overdue` all start from their zero values.

Screening comes next. An `IntakeOfficer` screens each `RECEIVED` complaint with a `decision`. A decision of `ACCEPT` requires jurisdiction: either the incident took place in Oregon or the respondent's operating states include Oregon; accepting without jurisdiction is refused with `ERR_NO_JURISDICTION`. Acceptance moves the complaint to `ACCEPTED`, stamps the screening officer into `accepted_by_officer_id` — the anchor for the closure segregation rule of §2.7 — and logs a `STATE_CHANGED` event. A decision of `DECLINE` must name a `decline_reason` of `NO_JURISDICTION`, `OUT_OF_AUTHORITY`, or `DUPLICATE`; the complaint becomes `DECLINED`, its `closed_at` is stamped, and it remains `UNPUBLISHED` forever, because declined complaints never enter the public record.

Before screening, the filing consumer may simply withdraw: the complaint becomes `DECLINED` with `decline_reason` set to `WITHDRAWN` and `closed_at` stamped. A declined consumer otherwise gets exactly one appeal, which returns the complaint from `DECLINED` to `RECEIVED`, clears both `decline_reason` and `closed_at`, and flips `appeal_used` to true. A second appeal is refused with `ERR_APPEAL_ALREADY_USED`, and a withdrawn complaint can never be appealed.

Reading complaints back is ownership-scoped. The complaint list accepts optional `consumer_id`, `business_id`, `case_status`, and `publication_status` filters, but a `Consumer` caller's `consumer_id` filter must equal their own identifier and a `Business` caller's `business_id` filter theirs — a mismatch is refused with `ERR_NOT_RESOURCE_OWNER`. Fetching a single complaint carries the same ownership check for both party roles, while staff roles read freely.

### 3.3. Business Notification and the Response Cycle

Once a complaint stands `ACCEPTED`, an `IntakeOfficer` notifies the business, moving the case to `BUSINESS_NOTIFIED` and computing the `response_deadline`. A business whose `home_state` matches the complaint's `incident_state` receives thirty days from the moment of notification; an out-of-state business receives a fifteen-day extension on top, forty-five days in total. A response arriving at the exact deadline instant is timely — the clock sweep flips a case to overdue only when the current time has passed the deadline strictly.

When the sweep does flip a complaint from `BUSINESS_NOTIFIED` to `RESPONSE_OVERDUE`, two things happen beyond the status change. The complaint's `ever_response_overdue` flag is set to true, and it is never reset, no matter how the case ends. And the business's `overdue_response_count` gains one. Neither change recomputes the pattern score by itself: the overdue penalty attaches later, at the next terminal closure, when the recomputation of §3.8 counts every flagged complaint.

The respondent answers with a `response_text`, and the caller's identifier must match the complaint's `business_id`. Each submission creates a `BusinessResponse` whose `business_id` is copied from the complaint, whose `attempt_number` continues one past the complaint's current `response_attempts`, and whose `submitted_at` comes from the logical clock. The system derives `is_late` by comparing the submission time against the `response_deadline` — a late answer submitted from `RESPONSE_OVERDUE` is always late — stamps `response_received_at`, points `latest_response_id` at the new row, and moves the complaint to `RESPONSE_RECEIVED` from either `BUSINESS_NOTIFIED` or `RESPONSE_OVERDUE`. A complaint accepts at most three responses in its life; once `response_attempts` has reached three, further submissions are refused with `ERR_RESUBMISSION_CAP_REACHED`. Every response begins with a `response_status` of `SUBMITTED`.

An `IntakeOfficer` then reviews the response — only the latest response on the complaint, and only while its `response_status` remains `SUBMITTED`; reviewing anything else is refused with `ERR_INVALID_STATE`. A `verdict` of `SUFFICIENT` moves `response_status` to `SUFFICIENT` and leaves the complaint in `RESPONSE_RECEIVED`, where mediation may now be offered. A `verdict` of `INSUFFICIENT` moves `response_status` to `INSUFFICIENT_RETURNED` and sends the complaint back to `BUSINESS_NOTIFIED` to await resubmission: the original deadline does not move, the spent attempt still counts, and the three-attempt cap will apply to the next submission. The response collection supports optional `complaint_id` and `business_id` filters.

Offering mediation is the intake officer's fork. From `RESPONSE_RECEIVED` it requires the latest response to be `SUFFICIENT`, and from `RESPONSE_OVERDUE` it may proceed with no adequate response at all; either path lands the complaint in `MEDIATION_OFFERED`. Both paths close entirely while the respondent's `watch_status` is `FLAGGED` — the attempt is refused with `ERR_PATTERN_REFERRAL_REQUIRED` per §2.11.

### 3.4. Mediation Sessions: Scheduling, Confirmation, and Completion

With mediation offered, in progress, or stalled at an impasse, a `Mediator` proposes a session. The complaint must sit in `MEDIATION_OFFERED`, `MEDIATION_ACTIVE`, or `MEDIATION_IMPASSE`. The proposal names the `mediator_id` — which must be the caller's own identifier — the `room_id`, a `starts_at`, and an `ends_at` that must fall strictly after the start. The regulatory and capacity gates of §2.12 apply in their fixed order: the complaint's business must not appear in the mediator's `conflicted_business_ids` (`ERR_MEDIATOR_CONFLICT_OF_INTEREST`); the mediator must have caseload headroom (`ERR_MEDIATOR_CASELOAD_FULL`) and a clear calendar (`ERR_MEDIATOR_TIME_CONFLICT`), and the room must be free (`ERR_ROOM_TIME_CONFLICT`); the mediator must be `ACTIVE` and the room `OPERATIONAL` (`ERR_REFERENCED_ENTITY_INACTIVE`); and the proposed start must lie strictly in the future (`ERR_SESSION_IN_PAST`).

Two different calendar rules guard the two resources. The mediator's own calendar uses a half-open rule with a thirty-minute turnover buffer: a proposed session conflicts with an existing one when the proposed `starts_at` falls before the existing session's `ends_at` plus thirty minutes, and the existing session's `starts_at` falls before the proposed `ends_at` plus thirty minutes — so a mediator may start a new session exactly at the instant a previous one ends plus the buffer, but no earlier. Room bookings use a stricter closed-interval rule with no buffer at all: a conflict exists whenever the proposed `starts_at` falls at or before an existing booking's `ends_at` and that booking's `starts_at` falls at or before the proposed `ends_at`, which means two sessions that merely touch at the exact boundary instant already conflict. Both checks consider only sessions in `PROPOSED` or `CONFIRMED` belonging to that mediator or that room.

A mediator's `active_case_count` is exactly the number of their own sessions in `PROPOSED` or `CONFIRMED`, and the count is the cap's yardstick: creation is refused once the count has reached the mediator's `max_concurrent_cases`. Creation adds one to the count; decline, cancellation, and completion each subtract one; confirmation leaves it unchanged, because both `PROPOSED` and `CONFIRMED` already count. A newly created session starts with a `session_status` of `PROPOSED`, with `consumer_confirmed` and `business_confirmed` both false and `outcome` null, and its creation writes a `SESSION_SCHEDULED` event.

Confirmation is deliberately two-party. A `Consumer` caller sets only `consumer_confirmed`; a `Business` caller sets only `business_confirmed`; and each caller must be a party to the underlying complaint. When the second confirmation lands and both flags stand true, the session becomes `CONFIRMED` — and the complaint advances with it, from `MEDIATION_OFFERED` to `MEDIATION_ACTIVE` the first time, or from `MEDIATION_IMPASSE` back to `MEDIATION_ACTIVE` on re-engagement — and a `SESSION_CONFIRMED` event is written. Either party may instead decline while the session is still `PROPOSED`, moving it to `DECLINED`; and the owning mediator or a `UnitDirector` may cancel a session in `PROPOSED` or `CONFIRMED`, moving it to `CANCELLED`.

Once the session's start has arrived, the owning mediator records the result. Completing with an `outcome` — one of `PROGRESS`, `IMPASSE`, or `SETTLEMENT_REACHED` — moves the session to `COMPLETED`; an `IMPASSE` result also drops the complaint from `MEDIATION_ACTIVE` to `MEDIATION_IMPASSE`, while the other two results leave the complaint where it stands. Completing with `no_show` set to true and no `outcome` instead records a `NO_SHOW`. Either form of completion releases the caseload slot. The re-engagement loop then closes when a later session on the same complaint reaches `CONFIRMED`, lifting the complaint back to `MEDIATION_ACTIVE`. The session collection supports optional `complaint_id`, `mediator_id`, and `room_id` filters.

### 3.5. Negotiation: Settlement Offers and the Cooling-Off Period

Once a complaint sits in `MEDIATION_ACTIVE` or `MEDIATION_IMPASSE`, either party may put terms on the table. The tender names the `offered_by_role` — `CONSUMER` or `BUSINESS`, which must match the caller's own role — a `restitution_amount_cents` that may be zero but never negative (a negative amount draws `ERR_INVALID_AMOUNT`), an optional `non_monetary_terms` note, and the concurrency token described in §2.8. The new offer opens `TENDERED`, records the caller as `offered_by_id`, stamps `tendered_at` from the logical clock, and sets its `expires_at` fourteen days out. Each complaint numbers its offers from 1: the first offer carries `offer_seq` 1 and a null `parent_offer_id`. If an earlier offer on the same complaint is still `TENDERED`, the new offer supersedes it — the old one becomes `SUPERSEDED`, the new one's `parent_offer_id` points at it, and its `offer_seq` continues the chain — and the complaint's `version` advances by one, which is exactly what the stale-version guard protects. An `OFFER_TENDERED` event records the act.

An offer stays open while the current time is at or before its `expires_at`; the clock sweep marks it `EXPIRED` only once time has strictly passed that instant. Offers may be tendered or accepted only while the complaint itself remains in `MEDIATION_ACTIVE` or `MEDIATION_IMPASSE`.

The counter-party responds. A consumer-tendered offer requires a `Business` caller to answer it, and a business-tendered offer requires the `Consumer`; in both cases the caller must also be a party to the complaint. Acceptance of a `TENDERED` offer stamps `accepted_at` and sets `cooling_off_until` seventy-two hours later, then writes an `OFFER_ACCEPTED` event. Rejection moves the offer to `REJECTED`. The tendering party, meanwhile, may withdraw its own offer — the caller's identifier must match `offered_by_id` — moving it to `WITHDRAWN`.

Consumer-protection practice then gives the consumer a cooling-off period. While the current time remains strictly before `cooling_off_until`, the consumer may rescind an `ACCEPTED` offer; at the exact instant the cooling-off ends, or any time after, rescission is refused with `ERR_RESCISSION_WINDOW_EXPIRED` — and that same instant is when settlement execution first becomes permitted, as §3.6 describes. Rescission is also blocked with `ERR_INVALID_STATE` once a settlement sourced from the offer has reached `EXECUTED`, `FULFILLED`, or `BREACHED`. A valid rescission moves the offer to `RESCINDED`, writes an `OFFER_RESCINDED` event, and voids any settlement still in `DRAFT` that was sourced from the offer: that settlement becomes `SUPERSEDED` and its outstanding balance is written off to zero. The offer collection supports optional `complaint_id`, `parent_offer_id`, and `offer_status` filters.

### 3.6. Settlement Documentation, Execution, and Breach

When the parties have an accepted offer, the mediator documents it as a settlement. The source selection is deterministic: the settlement documents the non-rescinded `ACCEPTED` offer with the highest `offer_seq` on the complaint, recorded as `source_offer_id`. The write carries the concurrency token of §2.8 and, like a tender, advances the complaint's `version` by one. The new settlement copies `restitution_amount_cents` from its source offer and both `business_id` and `consumer_id` from the complaint, computes its fee and totals as below, and opens with a `settlement_status` of `DRAFT` and `fulfilled_cents` at zero. Should the complaint already carry a settlement in `DRAFT`, `EXECUTED`, or `BREACHED`, the new document supersedes it: the old settlement becomes `SUPERSEDED`, its `outstanding_cents` is forced to zero as a write-off while its `fulfilled_cents` is preserved, and the complaint's `active_settlement_id` is repointed to the new document. A `SETTLEMENT_CREATED` event records the documentation.

The unit charges a tiered mediation fee keyed on the restitution subtotal only — never on the fee-inclusive total. When the restitution is below 100,000 cents, `mediation_fee_cents` is zero. When it is at least 100,000 cents and below 500,000 cents, the fee is two percent of the restitution, rounded half-up to whole cents. When it is 500,000 cents or more, the fee is two percent of the first 500,000 cents plus one percent of the excess above 500,000 cents, the sum rounded half-up to whole cents. The `total_due_cents` is then the restitution plus the fee. Keying matters: a restitution of 600,000 cents yields a fee of 11,000 cents and a `total_due_cents` of 611,000 cents, whereas the same rate mistakenly applied to the fee-inclusive total would produce 11,110 and 611,110. While a settlement stands in `DRAFT`, `EXECUTED`, `FULFILLED`, or `BREACHED`, its `outstanding_cents` is its restitution minus its `fulfilled_cents`.

Execution is the mediator's second act, and it must wait out the cooling-off: the current time must be at or past the source offer's `cooling_off_until`, or the attempt is refused with `ERR_COOLING_OFF_ACTIVE`. Execution stamps `executed_at`, sets the `due_date` thirty days later, moves the complaint from `MEDIATION_ACTIVE` or `MEDIATION_IMPASSE` into `SETTLEMENT_PENDING` with `active_settlement_id` pointing at the executed document, and writes a `SETTLEMENT_EXECUTED` event. A settlement whose restitution is zero needs no payment: the complaint passes straight through to `SETTLED` within the same request, with the full closure ritual of §3.8.

When the `due_date` has strictly passed and money remains outstanding, an `IntakeOfficer` or the `UnitDirector` may mark the settlement `BREACHED`; marking too early — current time at or before the `due_date` — or with nothing outstanding draws `ERR_BREACH_NOT_DUE`. Breach reopens negotiation: the complaint falls back from `SETTLEMENT_PENDING` to `MEDIATION_IMPASSE`, and a `SETTLEMENT_BREACHED` event is written. A settlement reaches `FULFILLED` only through payment allocation, the subject of §3.7. The settlement collection supports optional `complaint_id`, `business_id`, `consumer_id`, and `source_offer_id` filters.

### 3.7. Restitution Payments: Pledge, Allocation, and Disbursement

A business pays restitution in lump sums. The `Business` caller pledges by naming its `business_id` — which must equal the caller's own identifier — an `amount_cents` strictly greater than zero (otherwise `ERR_INVALID_AMOUNT`), and an `allocation_method` of `CHRONOLOGICAL` or `PRO_RATA`; the method defaults to `CHRONOLOGICAL` when omitted and is fixed at pledge time. The pledge opens with a `payment_status` of `PLEDGED`, its `allocations` list empty and its `received_at` null. The payment collection supports an optional `business_id` filter.

When the money arrives, an `IntakeOfficer` marks the payment received. The fiscal gate runs first: the amount may not exceed the sum of `outstanding_cents` across this business's settlements in `EXECUTED` or `BREACHED` that still carry a positive outstanding balance, and an over-large payment is refused with `ERR_RESTITUTION_EXCEEDS_OUTSTANDING`, remaining `PLEDGED`. Eligible obligations are then ordered by their complaints' `filing_seq`, ascending — filing sequence numbers are unique within a business, so no tie is possible and record identifiers are never consulted for ordering.

The two allocation methods diverge from there. Under `CHRONOLOGICAL`, the payment fills each obligation completely, in filing order, before moving to the next, and the final obligation touched may receive only a partial fill. Under `PRO_RATA`, each obligation's provisional share is the payment amount multiplied by that obligation's outstanding balance and divided by the total outstanding across all eligible obligations, with every line rounded half-up to whole cents first; the lines are then reconciled cent by cent — if the shares fall short of the payment, one cent at a time is added to lines in ascending filing order, cycling through them, until the payment is fully distributed, and if the shares overshoot, one cent at a time is removed from lines in descending filing order until the books balance. The methods genuinely differ: a payment of 10,000 cents against obligations of 6,000 cents (the earlier filing) and 5,000 cents allocates 6,000 and 4,000 chronologically, but 5,455 and 4,545 pro rata.

Marking received stamps `received_at`, moves the payment to `ALLOCATED`, and records the computed breakdown in `allocations` as entries of `settlement_id`, `complaint_id`, `filing_seq`, and `allocated_cents`. Every allocated line then cascades. The target settlement's `fulfilled_cents` grows and its `outstanding_cents` shrinks by the allocated amount. A settlement whose outstanding reaches exactly zero becomes `FULFILLED`, with `fulfilled_at` stamped. And the complaint behind a freshly fulfilled settlement moves from `SETTLEMENT_PENDING` to `SETTLED`, with the closure ritual of §3.8 — `closed_at`, embargo or suppression, pattern recomputation — firing in full. Each affected complaint receives a `PAYMENT_ALLOCATED` event, whose `note` carries the allocation detail.

A payment can be sent back — a bounced check, a recalled transfer — but only while none of the complaints it funded has reached `SETTLED`; otherwise the return is refused with `ERR_INVALID_STATE`. A valid return moves the payment to `RETURNED` and reverses everything: each settlement's `fulfilled_cents` is decremented and its `outstanding_cents` restored, any settlement that had become `FULFILLED` reverts to `EXECUTED` with `fulfilled_at` cleared to null, the `allocations` list is emptied, and every affected complaint receives a `PAYMENT_RETURNED` event. A payment that stands is eventually disbursed to the consumers by an `IntakeOfficer`, moving it to `DISBURSED` and writing a `PAYMENT_DISBURSED` event for each allocated complaint — the consumer-facing notification that money is on its way.

### 3.8. Enforcement Referral and Unresolved Closure

Three endings share a closing ritual. Whether a case ends `SETTLED`, `CLOSED_UNRESOLVED`, or `REFERRED_ENFORCEMENT`, the system stamps `closed_at` from the logical clock, moves the publication axis from `UNPUBLISHED` to `EMBARGOED` when the consumer gave `publication_consent` — or to `SUPPRESSED` when they did not — and recomputes the business's pattern score as described below.

Referral to enforcement is available at almost any working stage: from `ACCEPTED`, `BUSINESS_NOTIFIED`, `RESPONSE_RECEIVED`, `RESPONSE_OVERDUE`, `MEDIATION_OFFERED`, `MEDIATION_ACTIVE`, or `MEDIATION_IMPASSE`, an `IntakeOfficer`, a `Mediator`, or the `UnitDirector` may refer the case, supplying a `reason` narrative. Referral creates an `EnforcementReferral` in `PENDING_REVIEW`, recording the caller as `referred_by_user_id` with their `referred_by_role` and snapshotting the business's current pattern score into `pattern_score_at_referral`. The complaint becomes `REFERRED_ENFORCEMENT`, and the closing ritual fires.

An `EnforcementAttorney` then reviews the referral — but never one they filed themselves, since a reviewer whose identifier matches `referred_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`. A `decision` of `ACCEPT` keeps the case with enforcement: the referral becomes `ACCEPTED`, `reviewed_by_user_id` is stamped, and the complaint remains `REFERRED_ENFORCEMENT`. A `decision` of `RETURN` sends the case back: the referral becomes `RETURNED_TO_MEDIATION`, the complaint reverts to `MEDIATION_IMPASSE`, its `closed_at` is cleared, an embargo that never matured rolls back from `EMBARGOED` to `UNPUBLISHED`, and the pattern score is recomputed with the complaint no longer counting as closed. The referral collection supports optional `complaint_id`, `business_id`, and `referral_status` filters.

When mediation simply cannot help, an `IntakeOfficer` may close the case without resolution from `RESPONSE_RECEIVED`, `RESPONSE_OVERDUE`, `MEDIATION_OFFERED`, `MEDIATION_ACTIVE`, or `MEDIATION_IMPASSE`. The segregation rule of §2.7 bars the officer who originally accepted the complaint — the caller's identifier must differ from `accepted_by_officer_id`, else `ERR_SEGREGATION_OF_DUTIES`. Nothing may be left in flight: no offer in `TENDERED` or `ACCEPTED`, no settlement in `DRAFT`, `EXECUTED`, or `BREACHED`, and no session in `PROPOSED` or `CONFIRMED`. The closing officer must also leave the consumer a path forward — `alternative_options` must be a non-empty list drawn from `SMALL_CLAIMS`, `PRIVATE_ATTORNEY`, `BBB`, `FEDERAL_AGENCY`, and `CLASS_ACTION`, with anything else rejected as an invalid request — and a `closure_summary` is recorded with the case. The complaint becomes `CLOSED_UNRESOLVED`, `closed_by_officer_id` is stamped, and the closing ritual fires.

`SETTLED` and `CLOSED_UNRESOLVED` are absorbing: no further case transitions exist, and any action attempted against a finished case draws `ERR_INVALID_STATE`. Only a `DECLINED` complaint ever reopens, and only through the single appeal of §3.2.

Every terminal closure — and every referral return that un-closes a case — recomputes the respondent's `pattern_score`. The eligible set is the business's complaints with `closed_at` set, a `case_status` of `SETTLED`, `CLOSED_UNRESOLVED`, or `REFERRED_ENFORCEMENT`, and a closure date within the trailing 730 days; `DECLINED` complaints never count. Each eligible complaint contributes a weight by outcome — 10 for `SETTLED`, 15 for `CLOSED_UNRESOLVED`, 25 for `REFERRED_ENFORCEMENT` — plus a flat penalty of 5 points if its `ever_response_overdue` flag stands, counted once per complaint. The raw sum is then scaled by the business's `size_tier` — multiplied by 1.0 for `SMALL`, 0.75 for `MEDIUM`, or 0.5 for `LARGE` — and the product is rounded half-up to a whole number, the single rounding point of the computation, and finally clamped between 0 and 1,000 inclusive. Identical history therefore scores differently by size: a raw sum of 30 becomes 30 for a `SMALL` business, 23 for a `MEDIUM` one (22.5 rounding half-up), and 15 for a `LARGE` one. The recomputed score drives the watch bands of §2.11, including the `FLAGGED` bar on mediation offers.

### 3.9. Publication, Public Statistics, and Scam Alerts

Publication follows the second axis of §2.10. A case that closes with consumer consent sits `EMBARGOED` for ten days measured from `closed_at`; the clock sweep publishes it — moving it to `PUBLISHED` — once the current time reaches or passes that ten-day mark, the boundary day itself included. Publication increments the business's `published_complaint_count`, recomputes its rating, and writes a `PUBLISHED` event. A consumer who later regrets going public may retract: retraction moves a `PUBLISHED` complaint to `REDACTED`, decrements `published_complaint_count`, removes the complaint's demerit, and recomputes the rating again.

A business's public rating begins at 100 and loses demerits for each published complaint by outcome: 5 for `SETTLED`, 15 for `CLOSED_UNRESOLVED`, 25 for `REFERRED_ENFORCEMENT`. The `rating_score` is 100 minus the total effective demerits and never falls below zero. Only complaints currently `PUBLISHED` count — `EMBARGOED`, `SUPPRESSED`, `REDACTED`, and `UNPUBLISHED` complaints are all invisible to the rating. The `rating_tier` bands on inclusive lower bounds: `A` at 90 or above, `B` at 70 or above, `C` at 40 or above, and `D` below 40.

Two rating variants exist under `rating_method`. The default `LIFETIME` sums demerits over every published complaint regardless of age. `ROLLING_12M` weights each published complaint's demerit in full when its publication date falls within the trailing 365 days, and at one quarter otherwise; the weighted demerit sum is rounded half-up to a whole number first, and only then subtracted from 100 — so a single 15-demerit complaint published fourteen months ago contributes 3.75 into that rounding step. The rating is recomputed whenever a complaint is published or retracted, and whenever the `UnitDirector` switches the business's rating method as described in §3.1. The rating view reports `rating_score`, `rating_tier`, `rating_method`, `published_complaint_count`, `pattern_score`, and `watch_status` together.

The public statistics view counts only `PUBLISHED` complaints: `published_total` overall, then `settled_count`, `unresolved_count`, and `referred_count` by outcome, plus `average_days_to_close` — the mean of the whole-day spans between `filed_at` and `closed_at` across the published complaints, rounded half-up to whole days, and zero when nothing has been published. Embargoed complaints remain invisible to statistics until the sweep publishes them.

Public education runs through scam alerts. An `IntakeOfficer` or the `UnitDirector` drafts an alert with a `title`, a `body`, a `scam_category` — one of `PHISHING`, `IMPERSONATION`, `ADVANCE_FEE`, `FAKE_CHARITY`, `TECH_SUPPORT`, `ROMANCE`, or `OTHER` — a `severity` of `LOW`, `ELEVATED`, `HIGH`, or `CRITICAL`, and optionally a `related_business_id`, a `related_complaint_id`, and a list of `education_topics`. The drafter is recorded as `drafted_by_user_id`, and the alert begins in `DRAFT`. Publication is a `UnitDirector` act with two guards: the publisher must differ from the drafter (`ERR_SEGREGATION_OF_DUTIES`), and no other alert with the same `title` and `related_business_id` may already stand in `DRAFT` or `PUBLISHED` (`ERR_DUPLICATE_ACTIVE_ALERT`). Publishing stamps `published_at` and moves the alert to `PUBLISHED`; archiving later moves it to `ARCHIVED`. The alert feed — list and detail — is open to the public, and the list accepts optional `related_business_id`, `related_complaint_id`, and `alert_status` filters.

## 4. Endpoint Definitions

Operations that create a new resource — registrations, complaint filings, responses, sessions, offers, settlements, payment pledges, referrals, and alerts — return `201 Created`. Operations that modify an existing resource, drive a state transition, or answer a computed read return `200 OK`. The complete request and response shapes for each operation are defined by the narratives of §3; this table is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/consumer-protection/_clock/set_current_utc` | Advance the logical clock and run the ordered sweep | UnitDirector |
| POST | `/consumer-protection/consumers` | Register a consumer (self-service) | Anonymous |
| GET | `/consumer-protection/consumers/{consumerId}` | Get a consumer | Consumer, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| POST | `/consumer-protection/businesses` | Register a business | Anonymous |
| GET | `/consumer-protection/businesses` | List businesses (public directory) | Anonymous, Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| GET | `/consumer-protection/businesses/{businessId}` | Get a business | Anonymous, Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| POST | `/consumer-protection/businesses/{businessId}/rating-method` | Switch the rating variant and recompute the rating | UnitDirector |
| GET | `/consumer-protection/businesses/{businessId}/rating` | Computed read: current rating view | Anonymous, Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| GET | `/consumer-protection/businesses/{businessId}/complaint-statistics` | Computed read: published-complaint statistics | Anonymous, Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| POST | `/consumer-protection/mediators` | Register a mediator | UnitDirector |
| GET | `/consumer-protection/mediators/{mediatorId}` | Get a mediator | Mediator, IntakeOfficer, EnforcementAttorney, UnitDirector |
| POST | `/consumer-protection/mediators/{mediatorId}/deactivate` | Move a mediator from ACTIVE to INACTIVE | UnitDirector |
| GET | `/consumer-protection/mediation-rooms` | List mediation rooms | Mediator, IntakeOfficer, UnitDirector |
| POST | `/consumer-protection/mediation-rooms` | Register a mediation room | UnitDirector |
| GET | `/consumer-protection/mediation-rooms/{roomId}` | Get a mediation room | Mediator, IntakeOfficer, UnitDirector |
| POST | `/consumer-protection/mediation-rooms/{roomId}/take-out-of-service` | Move a room from OPERATIONAL to OUT_OF_SERVICE | UnitDirector |
| POST | `/consumer-protection/complaints` | File a complaint (filing window, duplicate check, jurisdiction worksheet) | Consumer |
| GET | `/consumer-protection/complaints` | List complaints; party callers must scope filters to themselves | Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| GET | `/consumer-protection/complaints/{complaintId}` | Get a complaint; party callers must own it | Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| POST | `/consumer-protection/complaints/{complaintId}/screen` | Screen for jurisdiction: accept or decline | IntakeOfficer |
| POST | `/consumer-protection/complaints/{complaintId}/appeal` | Appeal a declined complaint (once, never after withdrawal) | Consumer |
| POST | `/consumer-protection/complaints/{complaintId}/withdraw` | Withdraw an unscreened complaint | Consumer |
| POST | `/consumer-protection/complaints/{complaintId}/notify-business` | Notify the business and compute the response deadline | IntakeOfficer |
| POST | `/consumer-protection/complaints/{complaintId}/business-responses` | Submit a business response | Business |
| POST | `/consumer-protection/complaints/{complaintId}/offer-mediation` | Offer voluntary mediation | IntakeOfficer |
| POST | `/consumer-protection/complaints/{complaintId}/close-unresolved` | Close the case without resolution | IntakeOfficer |
| POST | `/consumer-protection/complaints/{complaintId}/retract-publication` | Retract a published complaint | Consumer |
| POST | `/consumer-protection/complaints/{complaintId}/refer-enforcement` | Refer the case to the enforcement division | IntakeOfficer, Mediator, UnitDirector |
| GET | `/consumer-protection/business-responses` | List business responses | Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| GET | `/consumer-protection/business-responses/{responseId}` | Get a business response | Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| POST | `/consumer-protection/business-responses/{responseId}/review` | Review a response: sufficient or insufficient-returned | IntakeOfficer |
| POST | `/consumer-protection/complaints/{complaintId}/mediation-sessions` | Propose a mediation session | Mediator |
| GET | `/consumer-protection/mediation-sessions` | List mediation sessions | Consumer, Business, Mediator, IntakeOfficer, EnforcementAttorney, UnitDirector |
| GET | `/consumer-protection/mediation-sessions/{sessionId}` | Get a mediation session | Consumer, Business, Mediator, IntakeOfficer, EnforcementAttorney, UnitDirector |
| POST | `/consumer-protection/mediation-sessions/{sessionId}/confirm` | Confirm attendance (each party confirms only its own side) | Consumer, Business |
| POST | `/consumer-protection/mediation-sessions/{sessionId}/decline` | Decline a proposed session | Consumer, Business |
| POST | `/consumer-protection/mediation-sessions/{sessionId}/cancel` | Cancel a proposed or confirmed session | Mediator, UnitDirector |
| POST | `/consumer-protection/mediation-sessions/{sessionId}/complete` | Complete a confirmed session (with outcome, or as a no-show) | Mediator |
| POST | `/consumer-protection/complaints/{complaintId}/settlement-offers` | Tender a settlement offer (supersedes the open offer; concurrency-guarded) | Consumer, Business |
| GET | `/consumer-protection/settlement-offers` | List settlement offers | Consumer, Business, Mediator, IntakeOfficer, EnforcementAttorney, UnitDirector |
| GET | `/consumer-protection/settlement-offers/{offerId}` | Get a settlement offer | Consumer, Business, Mediator, IntakeOfficer, EnforcementAttorney, UnitDirector |
| POST | `/consumer-protection/settlement-offers/{offerId}/accept` | Counter-party accepts a tendered offer | Consumer, Business |
| POST | `/consumer-protection/settlement-offers/{offerId}/reject` | Counter-party rejects a tendered offer | Consumer, Business |
| POST | `/consumer-protection/settlement-offers/{offerId}/withdraw` | Tendering party withdraws its own offer | Consumer, Business |
| POST | `/consumer-protection/settlement-offers/{offerId}/rescind` | Consumer rescinds an accepted offer inside the cooling-off | Consumer |
| POST | `/consumer-protection/complaints/{complaintId}/settlements` | Document the latest accepted offer as a settlement (concurrency-guarded) | Mediator |
| GET | `/consumer-protection/settlements` | List settlements | Consumer, Business, Mediator, IntakeOfficer, EnforcementAttorney, UnitDirector |
| GET | `/consumer-protection/settlements/{settlementId}` | Get a settlement | Consumer, Business, Mediator, IntakeOfficer, EnforcementAttorney, UnitDirector |
| POST | `/consumer-protection/settlements/{settlementId}/execute` | Execute a draft settlement after the cooling-off | Mediator |
| POST | `/consumer-protection/settlements/{settlementId}/mark-breached` | Mark an overdue, underpaid settlement breached | IntakeOfficer, UnitDirector |
| POST | `/consumer-protection/businesses/{businessId}/restitution-payments` | Pledge a lump-sum restitution payment | Business |
| GET | `/consumer-protection/restitution-payments` | List restitution payments | Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| GET | `/consumer-protection/restitution-payments/{paymentId}` | Get a restitution payment | Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| POST | `/consumer-protection/restitution-payments/{paymentId}/mark-received` | Mark a pledge received and run allocation | IntakeOfficer |
| POST | `/consumer-protection/restitution-payments/{paymentId}/mark-returned` | Return an allocated payment and reverse its allocations | IntakeOfficer |
| POST | `/consumer-protection/restitution-payments/{paymentId}/disburse` | Disburse an allocated payment to consumers | IntakeOfficer |
| GET | `/consumer-protection/enforcement-referrals` | List enforcement referrals | Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| GET | `/consumer-protection/enforcement-referrals/{referralId}` | Get an enforcement referral | Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| POST | `/consumer-protection/enforcement-referrals/{referralId}/review` | Review a referral: accept or return to mediation | EnforcementAttorney |
| POST | `/consumer-protection/scam-alerts` | Draft a scam alert | IntakeOfficer, UnitDirector |
| GET | `/consumer-protection/scam-alerts` | List scam alerts (public education feed) | Anonymous, Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| GET | `/consumer-protection/scam-alerts/{alertId}` | Get a scam alert | Anonymous, Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| POST | `/consumer-protection/scam-alerts/{alertId}/publish` | Publish a draft alert (publisher differs from drafter) | UnitDirector |
| POST | `/consumer-protection/scam-alerts/{alertId}/archive` | Archive a published alert | UnitDirector |
| GET | `/consumer-protection/complaint-events` | List the append-only case event trail | Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |
| GET | `/consumer-protection/complaint-events/{eventId}` | Get a single case event | Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_AMOUNT` | 400 Bad Request |
| `ERR_CONSUMER_NOT_FOUND` | 404 Not Found |
| `ERR_BUSINESS_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLAINT_NOT_FOUND` | 404 Not Found |
| `ERR_MEDIATOR_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_RESPONSE_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_ALERT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DUPLICATE_COMPLAINT` | 409 Conflict |
| `ERR_UNIQUENESS_VIOLATION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MEDIATOR_TIME_CONFLICT` | 409 Conflict |
| `ERR_ROOM_TIME_CONFLICT` | 409 Conflict |
| `ERR_MEDIATOR_CASELOAD_FULL` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_ALERT` | 409 Conflict |
| `ERR_FILING_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_NO_JURISDICTION` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_PATTERN_REFERRAL_REQUIRED` | 422 Unprocessable Entity |
| `ERR_MEDIATOR_CONFLICT_OF_INTEREST` | 422 Unprocessable Entity |
| `ERR_REFERENCED_ENTITY_INACTIVE` | 422 Unprocessable Entity |
| `ERR_RESUBMISSION_CAP_REACHED` | 422 Unprocessable Entity |
| `ERR_APPEAL_ALREADY_USED` | 422 Unprocessable Entity |
| `ERR_SESSION_IN_PAST` | 422 Unprocessable Entity |
| `ERR_COOLING_OFF_ACTIVE` | 422 Unprocessable Entity |
| `ERR_RESCISSION_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_BREACH_NOT_DUE` | 422 Unprocessable Entity |
| `ERR_RESTITUTION_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
