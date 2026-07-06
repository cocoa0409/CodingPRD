# Zoning Entitlement API — Product Requirements Document

## 1. Introduction

Municipal planning departments shepherd land-use requests — variances, rezones, conditional use permits, and subdivisions — through a long, statute-driven pipeline: intake and completeness screening, public-notice mailing, a scheduled hearing before a planning commission or city council, a decision accompanied by findings of fact and conditions of approval, a fixed appeal window, and finally the recording of a subdivision plat with its associated impact fees. Each step is bound by legally mandated waiting periods and by separation-of-duties rules that prevent the same officer from both staffing and deciding a case.

This API models that pipeline end to end. It manages GIS parcel records, applicant registration, the entitlement application itself, the hearing calendar and its finite agenda, appeals, subdivision plats, and the tiered impact-fee ledger that attaches to a parcel. Because so much of the workflow is clock-driven — notice periods measured in whole days, appeal windows that must fully elapse before an entitlement vests, expiration dates that fall years after a decision — the server operates on a controllable **logical clock** rather than wall-clock time, so that time-dependent behavior is deterministic and testable.

The document is organized in two halves. Section 2 fixes the system-wide contracts: authentication, the response envelope, pagination, the shared resource properties, the ordering in which validations fire, and the cross-cutting invariants (cascading parcel status, optimistic concurrency, segregation of duties, monetary precision, and the conserved fee-liability ledger). Section 3 walks the business workflows in the order a real case travels through the office. Sections 4 and 5 summarize the endpoints and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401). If the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `Applicant`, `Planner`, `Clerk`, `Commissioner`, and `Admin`.

- When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` entity. Ownership checks on any resource that references an applicant compare that resource's `applicant_id` foreign key to `X-User-ID`. An `Applicant` files and manages entitlement applications, submits and withdraws them, submits subdivision plats, files appeals, and pays impact fees.
- When `X-User-Role` is `Planner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — as `reviewed_by` on each completeness review the planner authors, and as `assigned_planner_user_id` on the application when the first completeness review is recorded — but does not compare it to any entity's `id`. A `Planner` records completeness determinations.
- When `X-User-Role` is `Clerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. A `Clerk` generates notices, builds the hearing calendar, places applications on agendas, effectuates and expires decisions, grants extensions, resolves appeals, and records or vacates plats.
- When `X-User-Role` is `Commissioner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. It is not tied to any entity's `id`, but it is compared against the application's `assigned_planner_user_id` to enforce separation of duties (see §2.9). A `Commissioner` records hearing decisions.
- When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. An `Admin` creates parcels and fee schedules, registers applicants, and drives the logical clock.

All read (GET) endpoints are available to every one of the five roles. Registering an applicant is available to both `Applicant` and `Admin`; filing an appeal is available to both `Applicant` and `Clerk`. All other write operations are restricted to the single role named in the endpoint table of §4.

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

List endpoints accept two query parameters. `limit` bounds the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items to skip and defaults to 0. A `limit` below 1 is clamped up to 1 and a `limit` above 100 is clamped down to 100; a negative `offset` is clamped up to 0; and a `limit` or `offset` that is absent or not a parseable integer falls back to its default.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with ties broken by the order in which the resources were created (their insertion sequence). The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources carry a standard set of system-managed fields:

- `id` — a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp recording the resource's last modification; it is refreshed on every mutation.
- `version` — an integer that starts at 1 on creation and increments by one on every mutation. It underpins optimistic concurrency (see §2.8).

Two record types are append-only evidentiary records and therefore carry **only** `id` and `created_at` — they have neither `updated_at` nor `version`: the completeness review (`CompletenessReview`) and the finding of fact (`Finding`). Every other entity — parcels, fee schedules, applicants, applications, notice mailings, hearings, agenda items, conditions of approval, appeals, plats, and impact-fee assessments — carries the full `id`/`created_at`/`updated_at`/`version` set.

The server keeps a **logical clock** that supplies "now" for every timestamp the system computes and for every time-based comparison. At startup the clock reads `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time. An `Admin` may move the clock to any instant by supplying the target time as `to_iso8601`; this is a test-driving capability with no other side effect than setting the clock.

### 2.5. Request Validation Order and Error Precedence

When more than one rule could reject a request, the checks fire in a fixed priority order, and the first failing check determines the error returned. Implementers must honor this order so that a lower-priority violation never masks a higher-priority one:

1. **Authentication** — headers present and `X-User-Role` a known role, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (401).
2. **Authorization** — the acting role is permitted for the operation, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every resource id named in the path or body is resolved left to right in path order (parcel, applicant, application, hearing, agenda item, appeal, plat, fee assessment, fee schedule), else the matching `ERR_..._NOT_FOUND` (404).
4. **Ownership** — for the owner-restricted applicant mutations — submitting or resubmitting an application, withdrawing an application, and paying an impact fee (compared against the `applicant_id` of the fee's plat's application) — the acting `Applicant`'s `X-User-ID` equals the target application's `applicant_id`, else `ERR_NOT_RESOURCE_OWNER` (403). Submitting a subdivision plat is not subject to this ownership check (any `Applicant` may submit a plat against an eligible application).
5. **State** — the target resource is in a state from which the requested transition is legal, else the state error appropriate to the transition (`ERR_INVALID_STATE`, `ERR_APPLICATION_NOT_ACCEPTED`, `ERR_HEARING_NOT_OPEN`, `ERR_AGENDA_FULL`, `ERR_FEE_NOT_ASSESSED`, `ERR_APPLICATION_NOT_EFFECTIVE`, and the like), each HTTP 409.
6. **Segregation of duties** — the deciding `Commissioner` is not the application's assigned planner, else `ERR_SEGREGATION_OF_DUTIES` (403).
7. **Optimistic concurrency** — `expected_hearing_version` matches the hearing's current `version`, else `ERR_STALE_HEARING_VERSION` (412).
8. **Findings requirement** — a decision supplies the required findings, else `ERR_FINDINGS_REQUIRED` (422).
9. **Notice present** — a `SENT` notice exists before agenda placement, else `ERR_NOTICE_MISSING` (409).
10. **Notice period** — the statutory waiting period is satisfied, else `ERR_NOTICE_PERIOD_NOT_MET` (422).
11. **Hearing calendar buffer** — a new hearing clears the minimum gap from same-body hearings, else `ERR_HEARING_CALENDAR_CONFLICT` (409).
12. **Parcel review overlap** — a first submit does not overlap another active review on the parcel, else `ERR_PARCEL_REVIEW_CONFLICT` (409).
13. **Appeal window** — an appeal is filed on or before the deadline, else `ERR_APPEAL_WINDOW_CLOSED` (422).
14. **Extension window** — an extension is requested inside its window, else `ERR_EXTENSION_WINDOW_CLOSED` (422).
15. **Extension cap** — the extension cap has not been reached, else `ERR_MAX_EXTENSIONS_REACHED` (409).
16. **Fee amount** — a payment equals the amount owed exactly, else `ERR_FEE_AMOUNT_MISMATCH` (402).
17. **Field-level validity** — required fields present, enums valid, acreage and lot counts positive, deficiency notes present when required, else `ERR_INVALID_REQUEST` (400). Field validity for a mutation is evaluated after authentication and existence, but where both a field-level defect and one of the specific business rules above would apply, the specific business rule takes precedence.

### 2.6. Nested Resource Retrieval

Several endpoints address a resource nested under a parent — for example, the completeness reviews, notices, conditions, findings, appeals, and agenda items belonging to a given application, or the agenda items and impact-fee assessment belonging to a given hearing or plat. For any such path, the server validates each identifier from left to right and returns the not-found error for the **first** identifier in the path that does not resolve, before considering anything further to its right. A request for the notices of a non-existent application therefore fails with `ERR_APPLICATION_NOT_FOUND`, never with a downstream error. Each resource type has its own not-found code: `ERR_PARCEL_NOT_FOUND` for a parcel, `ERR_FEE_SCHEDULE_NOT_FOUND` for a fee schedule, `ERR_APPLICANT_NOT_FOUND` for an applicant, `ERR_APPLICATION_NOT_FOUND` for an application, `ERR_HEARING_NOT_FOUND` for a hearing, `ERR_AGENDA_ITEM_NOT_FOUND` for an agenda item, `ERR_APPEAL_NOT_FOUND` for an appeal, `ERR_PLAT_NOT_FOUND` for a plat, and `ERR_FEE_NOT_FOUND` for an impact-fee assessment — each returned with HTTP 404 for the first unresolved identifier in path order.

### 2.7. Cascading Consistency and the Parcel Status Lifecycle

A parcel's `status` is never set directly by a client; it is driven entirely by cascades from the applications and plats that run with it. A parcel begins `AVAILABLE`. When an application is first submitted it moves to `UNDER_APPLICATION`; when that application vests it moves to `ENTITLED`; when a plat is recorded against an entitled subdivision it moves to `SUBDIVIDED`. The reverse edges restore prior states: withdrawal, denial-close, expiration, and an upheld appeal each return an entitled or under-application parcel to `AVAILABLE`, and vacating a recorded plat returns a `SUBDIVIDED` parcel to `ENTITLED`.

Whenever an operation mutates a resource — whether directly or as the downstream target of a cascade — that resource's `updated_at` is refreshed and its `version` is incremented (for entities that carry `version`). A single client action frequently touches several entities: for instance, recording a plat mutates the plat, its impact-fee assessment, the parent application, and the parcel, and every one of those mutations independently advances the affected resource's timestamps and version. Each such cascade is described in the relevant workflow in §3.

### 2.8. Optimistic Concurrency for Agenda Placement

A hearing holds a finite agenda, and each successful placement legitimately consumes a slot and advances the hearing's `version`. To prevent a clerk from placing an application against a stale view of that agenda, the placement operation is guarded by optimistic concurrency control.

A request that places an application on a hearing's agenda must include `expected_hearing_version`, carrying the `version` of the target hearing that the clerk last observed. If another writer has advanced the hearing's `version` since that read — because a competing placement already consumed a slot — the value no longer matches the hearing's current `version`, and the placement is rejected with `ERR_STALE_HEARING_VERSION` (HTTP 412) before capacity is re-read. This is the only endpoint that takes a version field; no other write requires one.

### 2.9. Segregation of Duties

The officer who decides a case must not be the officer who staffed it. When the first completeness review is recorded on an application, the reviewing planner's `X-User-ID` is captured as the application's `assigned_planner_user_id`. Later, when a `Commissioner` records the hearing decision, the acting commissioner's `X-User-ID` is compared against that stored `assigned_planner_user_id`; if they are equal, the decision is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This check applies to the decision-recording operation only.

### 2.10. Monetary Precision, Date Arithmetic, and the Fee-Liability Ledger

All monetary amounts in the system are integer cents; there are no fractional-cent values stored or returned. Impact-fee computations follow a pinned rounding discipline (detailed in §3.8): the tiered road charge and the pre-discount subtotal are carried exactly, the affordable-housing discount is rounded half up to whole cents exactly once, the administrative surcharge is computed on the discounted subtotal and rounded half up to whole cents exactly once, and the prior-payment credit cap is rounded half up to whole cents exactly once. All date computations — notice periods, appeal windows, entitlement lifespans, extensions, and calendar buffers — are performed as whole-day arithmetic in UTC.

Each parcel carries a conserved fee-liability figure, `assessed_fee_cents`, that is the sum of `total_fee_cents` across every non-voided impact-fee assessment (those in `ASSESSED` or `PAID` status) whose plat's application runs with that parcel. It is maintained incrementally: recording a plat adds that assessment's final fee to the parcel's `assessed_fee_cents`, and vacating a recorded plat removes it again, so that a record-then-vacate sequence restores the parcel's prior liability exactly. A newly created parcel starts with `assessed_fee_cents` of 0.

## 3. Business Logic & Workflows

### 3.1. Establishing the Record: Parcels, Fee Schedules, and Applicants

Before any case can be filed, an `Admin` seeds the reference data. A **parcel** is a GIS record keyed by its Assessor Parcel Number, `apn`, which is unique across parcels. It records the current `zoning_district` — one of `RES`, `COMM`, `IND`, or `AG` — and its `area_acres`, which must be greater than zero. Two GIS-derived neighbor counts drive public notice: `neighbor_parcel_count`, the number of parcels within the standard 300-foot notice radius (zero or greater), and `expanded_neighbor_count`, the number within the expanded 500-foot radius, which is never less than `neighbor_parcel_count`. A boolean `sensitive_area` (defaulting to false) marks parcels in a sensitive overlay that require the expanded radius. The parcel's `status` is initialized to `AVAILABLE`, and its conserved `assessed_fee_cents` liability starts at 0.

An **impact-fee schedule** captures the rates used to price a subdivision. It carries a `name` label and a set of rates in cents: `park_fee_per_lot_cents` (charged per lot), and a three-tier road charge — `road_fee_tier1_per_acre_cents` for the first band of acreage, `road_fee_tier2_per_acre_cents` for the middle band, and `road_fee_tier3_per_acre_cents` for acreage beyond the second band. It also carries three fractions and a cap: `admin_pct`, the administrative surcharge fraction applied to the discounted subtotal; `affordable_discount_pct`, the discount fraction applied when the application is an affordable-housing project; `credit_pct`, the fraction that caps prior-payment credit against the gross fee; and `fee_cap_cents`, the absolute ceiling on the gross fee.

An **applicant** is registered — by the applicant themselves or by an `Admin` — with a `full_name`, a contact `email`, and an optional `organization`.

### 3.2. Filing and the Completeness Review Loop

An `Applicant` opens a case by creating an **entitlement application**, which begins in `DRAFT`. Creation captures the `application_type` — one of `VARIANCE`, `REZONE`, `CUP`, or `SUBDIVISION` — together with the `parcel_id` of the GIS parcel the entitlement runs with, the `applicant_id` of the filing applicant, a free-text `requested_use` describing the relief sought, and an optional `affordable_housing` flag (defaulting to false) that later enables an impact-fee discount for subdivision plats. The application also maintains, over its life, a `revision_count`, an `assigned_planner_user_id`, a `decision`, a `decision_at`, an `appeal_deadline`, a `provisional_expiration_date`, an `effective_date`, a `final_expiration_date`, an `extension_count`, and a `review_window_closed_at` — all system-managed and described where they are set below.

Submitting the application moves it from `DRAFT` to `SUBMITTED`. Only the owning applicant may submit — the acting `X-User-ID` must equal the application's `applicant_id`, else `ERR_NOT_RESOURCE_OWNER`. On the **first** submit only, the server stamps `submitted_at` with the current clock reading (marking the start of the parcel's active review window), clears `review_window_closed_at` to null, and transitions the parcel from `AVAILABLE` to `UNDER_APPLICATION`. That first submit also enforces the parcel-overlap rule: the new application's active review interval, which runs from `submitted_at` (inclusive) up to its `review_window_closed_at` (exclusive), must not overlap the active review interval of any other application on the same parcel; an overlap is rejected with `ERR_PARCEL_REVIEW_CONFLICT`. An application's interval is active for as long as its `review_window_closed_at` is null.

A `Planner` screens a `SUBMITTED` application by recording a **completeness review**, supplying a `determination` of either `COMPLETE` or `INCOMPLETE`. Each review is stamped with a `cycle_number` equal to the application's current `revision_count` plus one, and with `reviewed_by` set to the planner's `X-User-ID`; if the application has no `assigned_planner_user_id` yet, it is set to this planner's `X-User-ID` on this review. An `INCOMPLETE` determination requires `deficiency_notes` describing the deficiencies; if they are absent the review is refused with `ERR_DEFICIENCY_NOTES_REQUIRED`, and it drives the application from `SUBMITTED` to `INCOMPLETE`. A `COMPLETE` determination drives the application from `SUBMITTED` to `ACCEPTED`. When the applicant resubmits an `INCOMPLETE` application, it returns to `SUBMITTED`, `revision_count` increases by one, and `submitted_at` is left unchanged; this `SUBMITTED` ↔ `INCOMPLETE` revision loop may repeat any number of times.

At any point before the case terminates, the owning applicant may withdraw it, moving it to `WITHDRAWN`. Withdrawal from `DRAFT`, `SUBMITTED`, `INCOMPLETE`, or `ACCEPTED` stamps `review_window_closed_at` with the current clock and returns the parcel to `AVAILABLE` (from `UNDER_APPLICATION`, where applicable). Withdrawal from `SCHEDULED` additionally cascades over the agenda: every still-`PLACED` agenda item for the application is set to `REMOVED`, and each removed item returns one slot to its hearing (that hearing's `agenda_slots_remaining` increases by one). Withdrawal from `DRAFT` requires the acting applicant to own the application (`ERR_NOT_RESOURCE_OWNER`).

### 3.3. Public Notice

Once a case is on file, a `Clerk` generates a **public notice mailing**, choosing a `notice_kind` of `MAILED`, `PUBLISHED`, or `POSTED`. The server stamps `mailed_at` with the current clock reading — this is the instant the statutory notice period begins — and computes the audience from the parcel. If the parcel's `sensitive_area` flag is set, the mailing reaches the expanded 500-foot audience: `recipient_count` is set to the parcel's `expanded_neighbor_count` and `used_expanded_radius` is recorded as true. Otherwise the standard 300-foot audience applies: `recipient_count` is the parcel's `neighbor_parcel_count` and `used_expanded_radius` is false. A notice begins in `SENT` status and moves to `VOIDED` only as part of an application-withdrawal cascade.

### 3.4. The Hearing Calendar and Agenda Placement

A `Clerk` builds the calendar by creating a **hearing** before a given `body` — either `PLANNING_COMMISSION` or `CITY_COUNCIL` — at a `scheduled_date`, with an `agenda_capacity` of at least one. A new hearing must clear a calendar buffer: for the same `body`, its `scheduled_date` must be at least 14 whole days from the `scheduled_date` of every existing hearing of that body that is not `CANCELLED`; a closer date is rejected with `ERR_HEARING_CALENDAR_CONFLICT`. A hearing is created in `SCHEDULED` status, and its `agenda_slots_remaining` is initialized equal to its `agenda_capacity`. At any time, `agenda_slots_remaining` equals `agenda_capacity` minus the count of agenda items on the hearing whose status is not `REMOVED`.

Placing an `ACCEPTED` application onto a hearing's agenda is the clerk action that drives the application from `ACCEPTED` to `SCHEDULED`. The placement request names the `application_id` to seat and, per §2.8, the `expected_hearing_version`. The placement is subject, in the fixed order of §2.5, to these gates: the application must be in `ACCEPTED` (`ERR_APPLICATION_NOT_ACCEPTED`) and the hearing must be `SCHEDULED` (`ERR_HEARING_NOT_OPEN`) with a free slot (`ERR_AGENDA_FULL`); the supplied `expected_hearing_version` must match the hearing's `version` (`ERR_STALE_HEARING_VERSION`); a `SENT` notice must already exist for the application (`ERR_NOTICE_MISSING`); and the notice period must be satisfied — the whole-day span from the notice's `mailed_at` (measured from the most recently mailed `SENT` notice when more than one exists) to the hearing's `scheduled_date` must be at least the statutory minimum for the body, which is 10 days for a `PLANNING_COMMISSION` hearing and 15 days for a `CITY_COUNCIL` hearing, else `ERR_NOTICE_PERIOD_NOT_MET`. On success the server creates a **hearing agenda item** in `PLACED` status, records its `hearing_id`, assigns its `agenda_position` as a one-based placement order following the assignment sequence (agenda items ordered by `created_at` ascending), decrements the hearing's `agenda_slots_remaining` by one, and increments the hearing's `version` by one.

A `Clerk` may cancel a hearing, moving it from `SCHEDULED` to `CANCELLED`, but only when it holds no `PLACED` agenda items; otherwise the cancellation is refused with `ERR_AGENDA_NOT_EMPTY`.

### 3.5. The Hearing Decision: Approve, Deny, or Continue

A `Commissioner` records the outcome of a hearing on the agenda item, supplying a `decision` of `APPROVE`, `DENY`, or `CONTINUE`. The addressed agenda item must still be `PLACED` and the parent application must be in `SCHEDULED` (else `ERR_INVALID_STATE`) — a decision may not be recorded on an item that has already been decided or continued — and the acting commissioner's `X-User-ID` must differ from the application's `assigned_planner_user_id` (§2.9), else `ERR_SEGREGATION_OF_DUTIES`.

An `APPROVE` decision requires at least one **finding** that supports approval; if none is supplied the decision is refused with `ERR_FINDINGS_REQUIRED`. On approval the agenda item's `decision` and `status` both become `APPROVED`, and the application moves from `SCHEDULED` to `DECIDED_APPROVED`. The server sets the application's `decision` to `APPROVED` and stamps `decision_at` with the current clock. It computes the `appeal_deadline` as `decision_at` plus a 15-day appeal window — the last instant an appeal may be filed. It also sets a `provisional_expiration_date`: for a `VARIANCE` or `CUP` this is `decision_at` plus 730 days, for a `SUBDIVISION` it is `decision_at` plus 1095 days, and for a `REZONE` it is null because a rezone never expires. From the payload's `conditions` array it creates one **condition of approval** per entry, each carrying a `condition_code` and `condition_text`, beginning `ACTIVE` and with `satisfied` false; from the payload's `findings` array it creates one **finding** per entry, each carrying a `finding_code`, `finding_text`, and a `supports_approval` flag.

A `DENY` decision likewise requires at least one finding supplied in the `findings` payload (`ERR_FINDINGS_REQUIRED`); the qualifying-support restriction applies to approvals only. On denial the agenda item's `decision` and `status` both become `DENIED`, and the application moves from `SCHEDULED` to `DECIDED_DENIED`. The server sets `decision` to `DENIED`, stamps `decision_at`, computes the `appeal_deadline` as `decision_at` plus the 15-day appeal window, and creates the finding rows from the payload. No conditions of approval and no provisional expiration are computed on a denial.

A `CONTINUE` decision rolls the case to a later hearing without deciding it. The payload names a `continued_to_hearing_id`, which must reference a `SCHEDULED` hearing that still has a free slot, else `ERR_HEARING_NOT_OPEN`. The current agenda item moves to `CONTINUED` with its `continued_to_hearing_id` recorded, and a fresh agenda item in `PLACED` status is created on the target hearing, decrementing that hearing's `agenda_slots_remaining` by one and incrementing that hearing's `version` by one. The application remains in `SCHEDULED`, so continuances may chain across successive hearings.

### 3.6. Appeals

Within the appeal window, an appeal may be filed against a decided application by either the `Applicant` or a `Clerk`. Filing captures the `application_id` under appeal, the `appellant_name`, and the stated `grounds`, and stamps `filed_at` with the current clock. The filing is valid only when `filed_at` is on or before the application's `appeal_deadline` (the deadline instant itself is still open); a later filing is rejected with `ERR_APPEAL_WINDOW_CLOSED`. An application that has not yet been decided has no `appeal_deadline`, so a filing against it is likewise rejected with `ERR_APPEAL_WINDOW_CLOSED`. A new appeal begins in `FILED` status.

A `Clerk` resolves a `FILED` appeal by supplying a `resolution` of `UPHELD`, `DENIED`, or `WITHDRAWN`. An `UPHELD` resolution reverses the approval: it is permitted only while the application is in `DECIDED_APPROVED` (else `ERR_INVALID_STATE`), moves the appeal to `UPHELD`, and drives the application from `DECIDED_APPROVED` to `DENIED_ON_APPEAL`. That reversal voids the entitlement's conditions — every `ACTIVE` condition of approval for the application becomes `VOIDED` — returns the parcel to `AVAILABLE`, and stamps the application's `review_window_closed_at` with the current clock. A `DENIED` or `WITHDRAWN` resolution lets the decision stand: the appeal moves to `DENIED` or `WITHDRAWN` respectively, and the application is untouched, free to proceed to effectuation once the window has elapsed.

### 3.7. Effectuation, Expiration, and Extension

After the appeal window has fully elapsed, a `Clerk` effectuates the case. Effectuation of an approved application is permitted only when the current clock is strictly past the `appeal_deadline` (else `ERR_APPEAL_WINDOW_OPEN`) and no appeal for the application is in `FILED` or `UPHELD` status (else `ERR_APPEAL_PENDING`). It drives the application from `DECIDED_APPROVED` to `EFFECTIVE`, sets `effective_date` equal to the `appeal_deadline` (the instant the entitlement vests), computes the authoritative `final_expiration_date` as `effective_date` plus the type's entitlement span — 730 days for a `VARIANCE` or `CUP`, 1095 days for a `SUBDIVISION`, and null for a `REZONE` — and transitions the parcel from `UNDER_APPLICATION` to `ENTITLED`. Because `effective_date` equals `appeal_deadline`, which is 15 days past `decision_at`, the `final_expiration_date` lands 15 days later than the earlier `provisional_expiration_date`.

Effectuating a denied application closes it: subject to the same window and pending-appeal gates, it drives the application from `DECIDED_DENIED` to `CLOSED`, returns the parcel to `AVAILABLE`, and stamps `review_window_closed_at`.

An `EFFECTIVE` entitlement expires once the clock passes its `final_expiration_date`. A `REZONE` never expires and is never eligible. When the clock is strictly past `final_expiration_date`, the case moves from `EFFECTIVE` to `EXPIRED`, the parcel returns from `ENTITLED` to `AVAILABLE`, and `review_window_closed_at` is stamped; an attempt to expire before that instant is refused with `ERR_NOT_YET_EXPIRED`.

Before expiration, a `Clerk` may grant a single extension while the application is `EFFECTIVE`. An extension is valid only when the clock falls inside the extension request window — the window that ends at `final_expiration_date` and opens 90 days before it, with both endpoints inclusive; a request outside that window is refused with `ERR_EXTENSION_WINDOW_CLOSED`. An extension may be granted at most once: if `extension_count` has already reached the cap of one, the request is refused with `ERR_MAX_EXTENSIONS_REACHED`. A granted extension pushes `final_expiration_date` out by 365 days and increases `extension_count` by one.

### 3.8. Subdivision Plats and Impact Fees

Only a `SUBDIVISION` application that has reached `EFFECTIVE` may be platted; an `Applicant` submits a **plat** naming the `application_id`, the `fee_schedule_id` whose rates are snapshotted onto the assessment, a `declared_lot_count` of at least one, a `declared_gross_acres` greater than zero, and an optional `prior_paid_fee_cents` (zero or greater) representing impact fee already paid on the parcel and eligible for credit. A plat against an application that is not a `SUBDIVISION` in `EFFECTIVE` state is refused with `ERR_APPLICATION_NOT_EFFECTIVE`. A new plat begins in `PENDING`, and the server immediately creates a **provisional impact-fee assessment** in `PROVISIONAL` status, linked to the plat by its `plat_id` and computing a `provisional_fee_cents` from the declared quantities.

**Computing the gross fee.** The gross fee is built from the plat's lot count and acreage against the snapshotted schedule. The park charge is `park_fee_per_lot_cents` multiplied by the lot count. The road charge is tiered by the marginal per-acre rates: the first 5 acres are charged at `road_fee_tier1_per_acre_cents`; the acreage above 5 acres and up to 20 acres — that is, the portion between the 5-acre and 20-acre boundaries, a band of at most 15 acres — is charged at `road_fee_tier2_per_acre_cents`; and any acreage beyond 20 acres is charged at `road_fee_tier3_per_acre_cents`. The road charge is the exact sum of those three tier amounts with no per-tier rounding, and the subtotal is the park charge plus the road charge, carried exactly. If the application's `affordable_housing` flag is set, a discount equal to the subtotal multiplied by `affordable_discount_pct`, rounded half up to whole cents, is subtracted from the subtotal; otherwise the discount is zero. The administrative surcharge is then the discounted subtotal multiplied by `admin_pct`, rounded half up to whole cents. The gross fee is the lesser of `fee_cap_cents` and the sum of the discounted subtotal and the administrative surcharge, and it is recorded on the assessment as `gross_fee_cents`.

**Applying the credit.** The prior-payment credit is derived from the gross fee, computed strictly after it and never from the net figure. The credit cap is the gross fee multiplied by `credit_pct`, rounded half up to whole cents; the credit applied, recorded as `credit_cents`, is the smaller of that cap and the plat's `prior_paid_fee_cents`. The net fee is the gross fee minus the applied credit. That net figure is what is stored as the assessment's fee at each stage: `provisional_fee_cents` while the assessment is `PROVISIONAL`, and `final_fee_cents` once it becomes `ASSESSED`. The assessment's authoritative `total_fee_cents` equals `provisional_fee_cents` while `PROVISIONAL` and equals `final_fee_cents` once `ASSESSED`.

**Provisional versus final.** The provisional assessment computed at plat submission uses the applicant-declared `declared_lot_count` and `declared_gross_acres` as a forward-looking estimate. When a `Clerk` records the plat, the actual `recorded_lot_count` (at least one) and `recorded_gross_acres` (greater than zero) are supplied and validated (`ERR_INVALID_REQUEST` if missing or invalid), and the final fee is recomputed by the identical gross-then-credit procedure using the recorded quantities; the final figure may diverge from the provisional one when the recorded quantities differ from the declared ones.

**Recording.** Recording a `PENDING` plat moves it to `RECORDED` and cascades: the assessment moves from `PROVISIONAL` to `ASSESSED` with `final_fee_cents` computed and `total_fee_cents` set to it; the parcel's `assessed_fee_cents` increases by that final fee (§2.10); the parent application moves from `EFFECTIVE` to `RECORDED` with its `review_window_closed_at` stamped; and the parcel moves from `ENTITLED` to `SUBDIVIDED`.

**Vacating and rejecting.** Vacating a `RECORDED` plat is the compensating action: the plat moves to `VACATED`, its assessment (whether `ASSESSED` or `PAID`) moves to `VOIDED`, the parcel's `assessed_fee_cents` is reduced by that assessment's `total_fee_cents`, the parent application moves from `RECORDED` back to `EFFECTIVE`, and the parcel moves from `SUBDIVIDED` back to `ENTITLED`. Vacating a still-`PENDING` plat instead rejects it: the plat moves to `REJECTED` and its `PROVISIONAL` assessment moves to `VOIDED`.

**Payment.** An `Applicant` pays an `ASSESSED` fee in full. The payment names an `amount_cents` that must equal the assessment's `total_fee_cents` exactly; a payment attempted while the assessment is not `ASSESSED` is refused with `ERR_FEE_NOT_ASSESSED`, and an amount that does not match is refused with `ERR_FEE_AMOUNT_MISMATCH`. On success the assessment moves from `ASSESSED` to `PAID` and its `amount_paid_cents` is set to `total_fee_cents`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including the state-transition actions such as submit, completeness, decide, effectuate, extend, resolve, record, vacate, and pay — return `200 OK`. The one exception among sub-resource creations is recording a completeness determination, which creates a new `CompletenessReview` record and returns `201 Created`. All list and fetch endpoints return `200 OK`. In the table below, "All roles" means every one of `Applicant`, `Planner`, `Clerk`, `Commissioner`, and `Admin`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Admin |
| POST | `/parcels` | Create a GIS parcel record | Admin |
| GET | `/parcels/{id}` | Get a parcel | All roles |
| POST | `/fee-schedules` | Create an impact-fee schedule | Admin |
| GET | `/fee-schedules/{id}` | Get a fee schedule | All roles |
| POST | `/applicants` | Register an applicant | Applicant, Admin |
| GET | `/applicants/{id}` | Get an applicant | All roles |
| POST | `/applications` | Create an entitlement application (DRAFT) | Applicant |
| GET | `/applications` | List applications; filter by applicant_id, parcel_id, status | All roles |
| GET | `/applications/{id}` | Get an application | All roles |
| POST | `/applications/{id}/submit` | Submit or resubmit an application | Applicant |
| POST | `/applications/{id}/completeness` | Record a completeness determination | Planner |
| GET | `/applications/{id}/completeness-reviews` | List completeness reviews for an application | All roles |
| POST | `/applications/{id}/notices` | Generate a public notice mailing | Clerk |
| GET | `/applications/{id}/notices` | List notice mailings for an application | All roles |
| POST | `/applications/{id}/withdraw` | Withdraw an application | Applicant |
| POST | `/applications/{id}/effectuate` | Close the appeal window and vest, close a denial, or expire | Clerk |
| POST | `/applications/{id}/extend` | Grant an expiration extension | Clerk |
| GET | `/applications/{id}/conditions` | List conditions of approval | All roles |
| GET | `/applications/{id}/findings` | List findings | All roles |
| GET | `/applications/{id}/appeals` | List appeals for an application | All roles |
| GET | `/applications/{id}/agenda-items` | List agenda items for an application | All roles |
| POST | `/hearings` | Create a hearing on the body's calendar | Clerk |
| GET | `/hearings/{id}` | Get a hearing | All roles |
| POST | `/hearings/{id}/agenda-items` | Place an accepted application on the hearing agenda | Clerk |
| GET | `/hearings/{id}/agenda-items` | List agenda items on a hearing | All roles |
| POST | `/hearings/{id}/cancel` | Cancel a scheduled hearing | Clerk |
| GET | `/agenda-items/{id}` | Get an agenda item | All roles |
| POST | `/agenda-items/{id}/decide` | Record a hearing decision (APPROVE / DENY / CONTINUE) | Commissioner |
| POST | `/appeals` | File an appeal within the appeal window | Applicant, Clerk |
| GET | `/appeals/{id}` | Get an appeal | All roles |
| POST | `/appeals/{id}/resolve` | Resolve an appeal (UPHELD / DENIED / WITHDRAWN) | Clerk |
| POST | `/plats` | Submit a subdivision plat | Applicant |
| GET | `/plats` | List plats; filter by application_id, fee_schedule_id | All roles |
| GET | `/plats/{id}` | Get a plat | All roles |
| POST | `/plats/{id}/record` | Record a pending plat (finalize fee; cascade) | Clerk |
| POST | `/plats/{id}/vacate` | Vacate a recorded plat or reject a pending plat | Clerk |
| GET | `/plats/{id}/impact-fee` | List the impact-fee assessment(s) for a plat | All roles |
| GET | `/impact-fees/{id}` | Get an impact-fee assessment | All roles |
| POST | `/impact-fees/{id}/pay` | Pay an assessed impact fee in full | Applicant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PARCEL_NOT_FOUND` | 404 |
| `ERR_FEE_SCHEDULE_NOT_FOUND` | 404 |
| `ERR_APPLICANT_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_HEARING_NOT_FOUND` | 404 |
| `ERR_AGENDA_ITEM_NOT_FOUND` | 404 |
| `ERR_APPEAL_NOT_FOUND` | 404 |
| `ERR_PLAT_NOT_FOUND` | 404 |
| `ERR_FEE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DEFICIENCY_NOTES_REQUIRED` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_APPLICATION_NOT_ACCEPTED` | 409 |
| `ERR_HEARING_NOT_OPEN` | 409 |
| `ERR_AGENDA_FULL` | 409 |
| `ERR_AGENDA_NOT_EMPTY` | 409 |
| `ERR_APPEAL_WINDOW_OPEN` | 409 |
| `ERR_APPEAL_PENDING` | 409 |
| `ERR_NOT_YET_EXPIRED` | 409 |
| `ERR_FEE_NOT_ASSESSED` | 409 |
| `ERR_APPLICATION_NOT_EFFECTIVE` | 409 |
| `ERR_FINDINGS_REQUIRED` | 422 |
| `ERR_NOTICE_MISSING` | 409 |
| `ERR_NOTICE_PERIOD_NOT_MET` | 422 |
| `ERR_HEARING_CALENDAR_CONFLICT` | 409 |
| `ERR_PARCEL_REVIEW_CONFLICT` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 |
| `ERR_EXTENSION_WINDOW_CLOSED` | 422 |
| `ERR_MAX_EXTENSIONS_REACHED` | 409 |
| `ERR_FEE_AMOUNT_MISMATCH` | 402 |
| `ERR_STALE_HEARING_VERSION` | 412 |
