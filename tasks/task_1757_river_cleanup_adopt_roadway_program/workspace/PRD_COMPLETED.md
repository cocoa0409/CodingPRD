# River Cleanup & Adopt-a-Roadway Program API — Product Requirements Document

## 1. Introduction

State environmental and transportation agencies have long run adopt-a-highway programs in which volunteer organizations take custodial responsibility for a stretch of public roadway. This program extends that model to river corridors: alongside traditional roadside segments, civic groups, businesses, schools, and faith organizations may now adopt riverbank reaches and take on scheduled litter cleanups under a formal, multi-year adoption agreement. The agency's obligations in return — recognition signage, supply support, and hazardous-materials response — all depend on trustworthy records of what each group actually did, and when.

Today the program runs on paper forms and spreadsheets, which makes the hardest questions unanswerable: Is an adopting group meeting its minimum cleanup frequency? Which depot's safety vests are still checked out, and to whom? Was a reported propane tank ever acknowledged and removed, and did anyone schedule a cleanup on top of it before it was? This API replaces that patchwork with a single auditable system covering the full adoption lifecycle — group registration, segment mapping, agreement review and renewal, event scheduling with safety briefings, supply custody, debris reporting, hazard escalation, and volunteer waivers including minor supervision.

This document is the product specification for that API. All program resources are mounted under the `/program` prefix. Because compliance is inherently time-driven — cleanup frequencies are measured over rolling windows, waivers expire, agreements lapse — the system runs on a controllable logical clock rather than the wall clock, and several lifecycle transitions are performed by scheduled sweeps whenever that clock advances.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes two distinct roles: `ProgramCoordinator` and `GroupLeader`.

A `ProgramCoordinator` is a member of the state agency's program staff. Coordinators map adoptable segments, create supply depots, review and decide agreements and renewals, suspend or terminate agreements, acknowledge and resolve hazard reports, install recognition signs, and drive the logical clock. When `X-User-Role` is `ProgramCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

A `GroupLeader` is the leader of an adopting organization. Leaders register their group, apply to adopt segments, schedule and run cleanup events, file waivers, debris reports, and hazard reports, and request signs and renewals. When `X-User-Role` is `GroupLeader`, `X-User-ID` is the `id` of the acting `AdopterGroup` — the identifier returned when the group is registered becomes that leader's `X-User-ID` thereafter. Ownership checks on any resource compare the `AdopterGroup` at the root of the resource's chain to `X-User-ID`: agreements are owned via their `group_id`; cleanup events, waivers, recognition signs, debris reports, and supply distributions are owned through the agreement they belong to; hazard reports are owned through the referenced event's agreement when an `event_id` is supplied on the report. A group record is the root of its own chain, so a leader may fetch only their own group's record. On the list endpoints for agreements, cleanup events, waivers, and supply distributions, a `GroupLeader`'s results are silently scoped to chains rooted at their own group rather than rejected; segment and hazard listings carry no such scoping. A `GroupLeader` touching a resource whose chain belongs to another group is rejected with `ERR_FORBIDDEN_OWNERSHIP`.

Failure to provide both headers, a blank value, or a role string that is not one of the two declared roles results in an `ERR_UNAUTHENTICATED` error. A well-formed identity whose role is simply not permitted on the target operation is rejected with `ERR_UNAUTHORIZED_ROLE`.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty random uppercase letters and digits.
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

A request that matches no declared route — an unknown path, or a known path with an unsupported method — is rejected with a 404 response whose `error_id` is `ERR_NOT_FOUND`.

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` that is not an integer or falls outside 1–100, or an `offset` that is not an integer or is negative, is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties on the timestamp broken by creation order — the resource created earlier at the same clock reading sorts first. Query-parameter filters match their field by exact equality; a filter value that matches no resource simply yields an empty page.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. `has_more` is true exactly when `offset` plus the number of items returned in the page is less than `total_count`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource in the program — adopter groups, road segments, adoption agreements, cleanup events, volunteer waivers, supply depots, supply distributions, hazard reports, and recognition signs — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp recording when the resource was first created. Entity timestamps are stamped from the logical clock of §2.5 and rendered at whole-second precision (`YYYY-MM-DDTHH:MM:SSZ`, with no fractional digits) — unlike the envelope's `api_request_timestamp`, which is wall-clock with three fractional digits.
- **`updated_at` (string):** an ISO 8601 UTC timestamp in the same whole-second logical-clock format recording the most recent modification.
- **`version` (integer):** a system-managed integer that starts at 1 on a newly created resource and increments by one on every modification of the resource, including every state transition.

This versioning rule is absolute: any mutation — a state transition, an amendment, a counter recomputation, or one hop of a multi-resource cascade — increments the affected resource's `version` by exactly one and refreshes its `updated_at`. When a cascade touches several resources, each touched resource is mutated independently.

Debris reports are the deliberate exception. A `DebrisReport` carries only `id` and `created_at`; `updated_at` and `version` are both absent, because debris reports are immutable once created. Their immutability is what makes program-wide debris totals stable across reads.

### 2.5. The Program-Wide Logical Clock

Every date comparison in the system — lead times, reporting windows, waiver validity, compliance windows, term boundaries — is evaluated against a server-side logical clock, never the wall clock. At startup the logical clock reads exactly 2026-08-01T00:00:00Z. Throughout this document, "today" and "the clock date" refer to this logical clock.

A coordinator-only capability, `POST /_clock/set_current_utc`, advances the logical clock to a supplied `to_iso8601` instant; sub-second digits on the supplied instant are discarded. The clock must move strictly forward; a request that does not advance it is rejected with `ERR_INVALID_REQUEST`. The response body carries the new clock reading as `current_utc`. Advancing the clock is never a quiet operation: each advance runs the program's four scheduled sweeps in a fixed order — first waiver expiry, then event no-show marking, then agreement auto-suspension for rolling non-compliance, and finally agreement auto-expiry past the term end. Each sweep's rules and cascades are defined in the lifecycle subsections of §3.

### 2.6. Standing, Cleanup Frequency, and the Two Compliance Windows

The program's central compliance obligation is a minimum cleanup frequency: every agreement must complete at least three cleanups per rolling year. The server measures this two different ways, and the two measures answer different questions.

The **rolling measure** drives the agreement's `standing` field and its `cleanups_completed_in_window` counter, and it fuels the suspension sweep and automatic reinstatement. The counter is the number of the agreement's cleanup events in status `COMPLETED` whose `scheduled_date` — the service date, not the completion date — falls within the trailing 365-day window that begins 365 days before today and ends today, both boundary days included. The `standing` field is derived from that count: the agreement is `COMPLIANT` when the count is at least three — exactly three qualifies. Below three, the agreement remains `NOT_EVALUATED` while its age, measured as today minus `term_start_date`, is under 180 days; once the agreement is at least 180 days old with a count still below three, it becomes `NON_COMPLIANT`. Both the counter and the standing are recomputed on every debris-report submission and, on every clock sweep, for agreements in `ACTIVE`, `SUSPENDED`, or `RENEWAL_REVIEW`. The auto-suspension sweep acts only on `ACTIVE` agreements that are at least 180 days old and whose rolling count is below three.

The **anniversary measure** answers a different question — whether an agreement has earned renewal — and it is evaluated only when a coordinator approves a renewal. The 24-month term is divided into two fixed 12-month windows anchored at `term_start_date`: the first window runs from the term start date up to but not including the first anniversary of the term start, and the second runs from that first anniversary up to but not including the second anniversary. Every one of these windows must hold at least three `COMPLETED` cleanups for renewal approval to be eligible; membership is again by `scheduled_date`. Because the two measures are anchored differently, the same completion history can be `COMPLIANT` under the rolling measure yet ineligible for renewal under the anniversary measure.

### 2.7. Supply Conservation and Depot Accounting

Supply depots are the custody backbone of the program. Each depot tracks on-hand stock in `bags_on_hand`, `vests_on_hand`, and `grabbers_on_hand`, and cumulative write-offs in `lost_vests_total` and `lost_grabbers_total`. At creation, the depot's `vests_pool_total` and `grabbers_pool_total` are pinned to the initial `vests_on_hand` and `grabbers_on_hand` respectively and never change afterward — they are the conserved-quantity baselines.

Vests and grabbers are returnables; bags are consumable and are never returned, so `bags_on_hand` only ever decreases through issuance. For each depot and each returnable item, the server enforces an exact conservation invariant after every issue, every return, every reconciliation, and every cascade: the depot's on-hand count for the item, plus the outstanding quantity across all of that depot's distributions still in `ISSUED` or `PARTIALLY_RETURNED`, plus the depot's cumulative lost total for the item, must equal the pinned pool total. A distribution's outstanding quantity is its issued count minus its returned count minus its written-off count. As a compensating pair, an issue followed by a full return of the same units leaves the depot's on-hand count identical to its pre-issue value.

### 2.8. Mileage Conservation Across the Program

A road segment's `mile_length` is the difference between its end and start mile markers, rounded half-up to two decimal places. A segment's `status` is entirely system-managed: it is `AVAILABLE` from creation and remains so while every agreement referencing it is `PENDING_REVIEW` or terminal, and it is `ADOPTED` while an agreement referencing it is in `ACTIVE`, `SUSPENDED`, or `RENEWAL_REVIEW`. No endpoint flips a segment's status directly; approval moves a segment from `AVAILABLE` to `ADOPTED`, and termination, expiry, or renewal denial moves it back from `ADOPTED` to `AVAILABLE`.

The program treats mapped mileage as a conserved quantity. After every segment creation and after every agreement approval, termination, expiry, or renewal denial, the miles carried by `AVAILABLE` segments plus the miles carried by `ADOPTED` segments must equal the total mapped mileage across all segments — a constant once the segment inventory is fixed. The compensating pair for this invariant: approving an agreement and later terminating it returns the program's available mileage to exactly its pre-approval value.

### 2.9. Optimistic Concurrency Control

Amending an adoption agreement is the one write operation guarded by optimistic concurrency control. The amendment request must carry `expected_agreement_version`, a non-optional field holding the agreement `version` the client last observed (a JSON integer; a decimal string whose digits form the integer is also accepted). If the agreement's current `version` differs — because a review decision, a suspension, an automatic reinstatement, or a prior amendment has advanced it since the client last read the agreement — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the agreement before retrying. No endpoint other than the agreement amendment takes a version field.

### 2.10. Precision, Rounding, and Derived Quantities

Distance values (`mile_length`, and the mileage totals in program metrics) are rounded half-up to two decimal places. Weight values (`official_weight_lbs`, per-material line weights, `completed_weight_lbs`, and program debris totals) are rounded half-up to one decimal place; for estimated debris reports, each material line is rounded first and the rounded lines are then summed — the rounding-precedes-summation order is pinned. Counts (cleanups, volunteers, supply units, renewals, losses) are integers. Supply allocation rounds each line item up to the next whole unit, and where a surcharge applies, the surcharge multiplication is followed by its own upward rounding. Volunteer age is computed in whole calendar years with a strict less-than comparison against the eighteen-year majority threshold. In all cases "round half up" is the rounding method. Month arithmetic — the 24-month term, the one-year waiver expiry, and the renewal term roll — is calendrical: the result keeps the source day-of-month, clamped down to the target month's last day when that month is shorter, so a February 29 start yields a February 28 anniversary in a non-leap year.

### 2.11. Validation Order and Reference Resolution

Every request is checked against a fixed sequence of rule families, and a failure surfaces the error of the earliest failing family:

1. **Authentication** — the headers rule of §2.1 (`ERR_UNAUTHENTICATED`).
2. **Role authorization** — the acting role must appear in the endpoint's authorized role list (`ERR_UNAUTHORIZED_ROLE`).
3. **Reference existence** — every referenced resource must resolve, each class with its own 404: adopter groups referenced by path or by a body's `group_id` (`ERR_GROUP_NOT_FOUND`); road segments (`ERR_SEGMENT_NOT_FOUND`); adoption agreements (`ERR_AGREEMENT_NOT_FOUND`); cleanup events (`ERR_EVENT_NOT_FOUND`); volunteer waivers, whether addressed by path, cited as a `supervisor_waiver_id`, or listed in `attendee_waiver_ids` (`ERR_WAIVER_NOT_FOUND`); supply distributions (`ERR_SUPPLY_NOT_FOUND`); the depot named by a supply-issuance body's `depot_id` (`ERR_DEPOT_NOT_FOUND`); hazard reports (`ERR_HAZARD_NOT_FOUND`); recognition signs (`ERR_SIGN_NOT_FOUND`). Where a path nests one resource under another — for example, a sign listing under an agreement — identifiers are validated strictly left to right, and the first unresolvable identifier produces its class's 404 before any later identifier is examined.
4. **GroupLeader ownership** — the chain-root comparison of §2.1 (`ERR_FORBIDDEN_OWNERSHIP`).
5. **Request shape** — required fields present, types and enum values valid, ranges respected: `expected_volunteers` at least 1; `mile_marker_end` strictly greater than `mile_marker_start`; `sign_text` between 1 and 60 characters; `dob` a date in the past; a `decision` value within the deciding endpoint's enumerated choices (`ERR_INVALID_REQUEST`).
6. **State guards** — the operation's required current status on its target resource (the family of 409 state errors), and, for agreement amendment, the optimistic-concurrency check of §2.9 (`ERR_STALE_VERSION`).
7. **Safety rules** — hazard blocks on scheduling, minor-guardian and supervisor rules on waivers, and briefing-attendee rules (the family of 422 safety errors).
8. **Temporal windows** — scheduling lead time, briefing and reporting windows, and the renewal window (the family of 422 timing errors).
9. **Business constraints** — segment availability, event day-slot uniqueness, measured-weight reconciliation, return-quantity caps, one-distribution-per-event, one-live-sign-per-agreement, renewal eligibility, and the completed-cleanup prerequisite for sign installation.
10. **Depot stock capacity** — evaluated last of all: a computed supply allocation is checked against depot on-hand only after every other rule has passed (`ERR_SUPPLY_STOCK_EXCEEDED`).

## 3. Business Logic & Workflows

### 3.1. Registering Groups and Mapping Adoptable Mileage

Everything begins with the adopting organization. A `GroupLeader` registers the group by supplying its public `name`, an `org_type` of `CIVIC`, `BUSINESS`, `SCHOOL`, `FAITH`, or `OTHER`, a `contact_name`, and a `contact_email`. The `id` returned for the new `AdopterGroup` becomes that leader's `X-User-ID` on every subsequent call, binding the leader's identity to the group record.

A `ProgramCoordinator` then maps the adoptable inventory. Each `RoadSegment` is created with a `route_name` (for example, "River Rd"), a `mile_marker_start` and a `mile_marker_end` — the end marker must be strictly greater than the start marker — a `segment_type` of `ROADWAY` for roadside segments or `RIVERBANK` for river cleanup reaches, and an optional `water_adjacent` flag that defaults to false and records whether the segment borders water. That flag matters later: water-adjacent segments carry a bag surcharge in supply allocation. The segment's `mile_length` is computed from the markers at creation per §2.8, and a new segment begins life `AVAILABLE`. Segment listings can be filtered by `status` and by `water_adjacent`; the `water_adjacent` filter accepts the strings `true` and `false` (case-insensitive) and rejects any other value with `ERR_INVALID_REQUEST`.

### 3.2. Adoption Agreements: Application, Review, Amendment, Suspension, and Termination

A `GroupLeader` applies to adopt a segment by submitting a payload containing the `group_id`, the `segment_id`, an agreement-level `contact_email`, and an optional `special_instructions` free-text note for the agency. The application is refused with `ERR_SEGMENT_NOT_AVAILABLE` when the segment is not `AVAILABLE` — a segment spanned by another agreement in `ACTIVE`, `SUSPENDED`, or `RENEWAL_REVIEW` is already `ADOPTED`. Filing an application does not itself change the segment's status: a segment whose agreements are all still `PENDING_REVIEW` remains `AVAILABLE`, so a second application on the same segment is accepted while the first awaits review, and the conflict between them is caught only at approval time. A successful application creates the `AdoptionAgreement` in `PENDING_REVIEW`: `renewal_count` starts at zero, `standing` starts `NOT_EVALUATED`, `cleanups_completed_in_window` starts at zero, `suspension_reason` is null, and both term dates are null until approval. Agreement listings can be filtered by `group_id`, `segment_id`, and `status`.

A `ProgramCoordinator` disposes of the application by recording a `decision` of `APPROVE` or `REJECT`, with an optional `note`. The review is only meaningful on a `PENDING_REVIEW` agreement; anything else draws `ERR_AGREEMENT_NOT_PENDING`. Approval additionally requires the segment to still be `AVAILABLE` — otherwise the decision fails with `ERR_SEGMENT_NOT_AVAILABLE`, which is how a double approval is caught. On approval the segment flips to `ADOPTED`, `term_start_date` is set to the clock date, `term_end_date` is set 24 months later, and `standing` is reset to `NOT_EVALUATED`. Rejection moves the agreement to `REJECTED`, a terminal state alongside `EXPIRED` and `TERMINATED`.

While an agreement is `ACTIVE` or `SUSPENDED`, the owning leader or a coordinator may amend its `contact_email` or `special_instructions` (a null `special_instructions` clears the note); amending an agreement in any other status fails with `ERR_AGREEMENT_NOT_ACTIVE`. The amendment is the OCC-guarded write of §2.9 and must carry `expected_agreement_version`; a stale value is rejected with `ERR_STALE_VERSION`. Because the amendment itself increments the agreement's `version`, two amendments in a row require a fresh read between them.

Suspension is the program's enforcement instrument, and it arrives by two paths. A coordinator may suspend an `ACTIVE` agreement directly, optionally supplying a `reason`; an agreement that is not `ACTIVE` refuses with `ERR_AGREEMENT_NOT_ACTIVE`. The second path is automatic: when a clock sweep recomputes an agreement's standing and finds it `NON_COMPLIANT` — at least 180 days old with fewer than three completed cleanups in the rolling window — the sweep suspends the agreement itself and records `suspension_reason` as `COMPLIANCE_DEFICIENCY`. On the coordinator path the supplied `reason` is recorded in `suspension_reason` instead. Either path runs the same three-link cascade: every child cleanup event in `SCHEDULED` or `POSTPONED` moves to `CANCELLED` — events already in `BRIEFING_DONE` are deliberately not touched — each cancelled event's supply distribution in `ISSUED` or `PARTIALLY_RETURNED` moves to `RECONCILED` with all outstanding returnables treated as returned and no loss recorded, and the issuing depot's `vests_on_hand` and `grabbers_on_hand` are restocked by the returned counts with the depot's `updated_at` refreshed.

Termination is final and available to both the coordinator and the owning leader, from any of `ACTIVE`, `SUSPENDED`, or `RENEWAL_REVIEW`; an agreement in any other status — terminal, or still `PENDING_REVIEW` — refuses with `ERR_AGREEMENT_TERMINAL`. An optional `reason` may accompany the request. The termination cascade is wider than the suspension cascade in exactly one respect: every non-terminal child event — `SCHEDULED`, `BRIEFING_DONE`, and `POSTPONED` alike — moves to `CANCELLED`, each such event's distribution in `ISSUED` or `PARTIALLY_RETURNED` is reconciled with outstanding returnables restocked to the depot and no loss recorded, any `INSTALLED` recognition sign under the agreement moves to `REMOVED`, and the segment returns to `AVAILABLE`.

A suspended agreement is not stuck: §3.6 describes how filing debris reports can lift it back to `ACTIVE` automatically.

### 3.3. Scheduling and Running Cleanup Events

Under an `ACTIVE` agreement, the owning `GroupLeader` schedules a cleanup by supplying the `agreement_id`, a `scheduled_date` (a single-day ISO calendar date), and the `expected_volunteers` headcount, which must be at least 1. Four families of guards apply, in the order of §2.11: the agreement-state guard rejects a non-`ACTIVE` agreement with `ERR_AGREEMENT_NOT_ACTIVE`; the safety guard refuses scheduling while any hazard report on the agreement's segment is in `REPORTED` or `ACKNOWLEDGED`, with `ERR_HAZARD_UNRESOLVED`; the temporal guard requires the `scheduled_date` to be at least 14 days after the clock date, rejecting earlier dates with `ERR_EVENT_TOO_SOON`; and the day-slot constraint forbids another live event — one in `SCHEDULED`, `BRIEFING_DONE`, or `POSTPONED` — on the same segment sharing the same `scheduled_date`, rejecting collisions with `ERR_EVENT_WINDOW_OVERLAP`. The slot rule is per calendar day and half-open in effect: events on adjacent days coexist freely. A new event starts `SCHEDULED` with `postpone_count` at zero, `briefing_attendee_count` at zero, and `completed_weight_lbs` null. Event listings filter by `agreement_id` and `status`.

Before volunteers pick up a single bag, the leader records the safety briefing — the acknowledgement of the traffic and water hazard protocol — by submitting the `attendee_waiver_ids` of everyone present. The checks here also follow §2.11 order: every listed waiver must first resolve (`ERR_WAIVER_NOT_FOUND`); the event must be `SCHEDULED`, else `ERR_EVENT_NOT_SCHEDULED`; each listed waiver must be `ACTIVE`, be unexpired — the clock date on or before its `expiry_date` — and belong to the event's agreement, else `ERR_WAIVER_INVALID_ATTENDEE` (an empty attendee list draws the same error); and for every minor in the attendee list, the waiver named by that minor's `supervisor_waiver_id` must also appear in the list, else `ERR_SUPERVISOR_ABSENT`. Timing closes the sequence: the briefing must happen on or before the event day, so a clock date later than `scheduled_date` is refused with `ERR_REPORT_WINDOW_CLOSED`. A recorded briefing moves the event to `BRIEFING_DONE` and sets `briefing_attendee_count` to the size of the attendee list.

Weather and life intervene, so events may be postponed. From `SCHEDULED` or `BRIEFING_DONE`, the leader postpones with an optional `reason`; an event in any terminal state — `COMPLETED`, `CANCELLED`, or `NO_SHOW` — refuses with `ERR_EVENT_TERMINAL`. Postponing moves the event to `POSTPONED`, increments `postpone_count`, and resets `briefing_attendee_count` to zero: a rescheduled event must be briefed again from scratch. While an event is `SCHEDULED`, the leader may also submit plain edits such as a revised `expected_volunteers`, and may likewise supply a new `scheduled_date` — subject to the same lead-time (`ERR_EVENT_TOO_SOON`) and day-slot (`ERR_EVENT_WINDOW_OVERLAP`) checks — while the event remains `SCHEDULED`. Supplying a new `scheduled_date` to a `POSTPONED` event is the reschedule path: the new date must again be at least 14 days past the clock date (`ERR_EVENT_TOO_SOON`) and must not collide with another live event's day-slot on the segment (`ERR_EVENT_WINDOW_OVERLAP`); on success the event returns to `SCHEDULED`. A `POSTPONED` event also accepts plain edits such as a revised `expected_volunteers`, with or without a new date. Any edit attempted on an event that is neither `SCHEDULED` nor `POSTPONED` — a `BRIEFING_DONE` event or a terminal one — draws `ERR_EVENT_TERMINAL`.

Cancellation moves an event from `SCHEDULED`, `BRIEFING_DONE`, or `POSTPONED` to `CANCELLED` and is open to the leader or a coordinator, with an optional `reason`; terminal events again refuse with `ERR_EVENT_TERMINAL`. Cancelling auto-reconciles the event's supply distribution: a distribution in `ISSUED` or `PARTIALLY_RETURNED` moves to `RECONCILED`, outstanding returnables are restocked to the depot, and no loss is recorded. Events that simply never happen are caught by the clock: when an advance carries the clock date past the `scheduled_date` of an event still in `SCHEDULED` or `POSTPONED`, the no-show sweep moves it to `NO_SHOW` with the same reconcile-and-restock cascade. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are the event's terminal states.

### 3.4. Volunteer Waivers and Minor Supervision

Participation requires a signed waiver, filed by the leader under a specific agreement. The registration payload carries the `volunteer_full_name`, the volunteer's `dob` as an ISO date that must lie in the past, and — where relevant — the optional `guardian_full_name`, `guardian_consent` (which defaults to false), and `supervisor_waiver_id` fields. The server stamps `signed_date` with the logical clock date at creation, computes `expiry_date` as one year after the signing date, and creates the waiver `ACTIVE`. A waiver remains `ACTIVE` while the clock date is on or before its `expiry_date`; the waiver-expiry sweep moves `ACTIVE` waivers whose expiry date has passed to `EXPIRED`, and the leader may revoke an `ACTIVE` waiver at any time — revoking anything else fails with `ERR_WAIVER_NOT_ACTIVE` — moving it to `REVOKED`. `EXPIRED` and `REVOKED` are terminal.

Minor status is computed at signing from whole calendar years: the volunteer's age is the largest whole number of years that can be added to `dob` without passing `signed_date`, and `is_minor` is true exactly when that age is strictly less than 18. The boundary is sharp — a volunteer whose eighteenth birthday falls exactly on the signing date is 18 and not a minor, while a `dob` one day later makes the volunteer 17 and a minor. A minor's waiver is accepted only with `guardian_full_name` present and `guardian_consent` true, else `ERR_MINOR_GUARDIAN_REQUIRED`, and its `supervisor_waiver_id` must reference a waiver that is `ACTIVE`, belongs to an adult — `is_minor` false — sits under the same agreement, and is not the waiver being created, else `ERR_SUPERVISOR_INVALID`. Adult waivers leave the guardian and supervisor fields null: any `guardian_full_name`, `guardian_consent`, or `supervisor_waiver_id` supplied on an adult waiver is discarded, with `guardian_full_name` and `supervisor_waiver_id` stored null and `guardian_consent` false. Waiver listings filter by `agreement_id`, `supervisor_waiver_id`, and `status`, which makes a supervisor's whole supervised crew easy to enumerate.

### 3.5. Supply Distribution and Depot Accounting

Coordinators provision the program by creating supply depots with a `name` and initial `bags_on_hand`, `vests_on_hand`, and `grabbers_on_hand`, each zero or greater. At that moment the conservation baselines `vests_pool_total` and `grabbers_pool_total` are pinned to the initial returnable stock, and the loss counters `lost_vests_total` and `lost_grabbers_total` start at zero; thereafter on-hand quantities are mutated only by issues, returns, loss write-offs, and cascades, never by direct edit.

For a non-terminal event under an `ACTIVE` agreement — a terminal event refuses issuance with `ERR_EVENT_TERMINAL` and a non-`ACTIVE` agreement with `ERR_AGREEMENT_NOT_ACTIVE` — the leader requests supplies by naming a `depot_id`. An unresolvable depot reference fails with `ERR_DEPOT_NOT_FOUND`, and because exactly one distribution may exist per event, a second issuance for the same event is refused with `ERR_SUPPLY_ALREADY_ISSUED`. The allocation is computed from the event and its segment: `vests_issued` is exactly the `expected_volunteers` count; `grabbers_issued` is one grabber per two volunteers, rounded up; and `bags_issued` starts from the volunteer count multiplied by two bags per volunteer per mile and by the segment's `mile_length`, rounded up to a whole bag — and when the segment is water-adjacent, that rounded quantity is multiplied by one and a quarter and rounded up again. For an event expecting 7 volunteers on a 2.0-mile water-adjacent reach, issuance is 7 vests, 4 grabbers, and 35 bags; the same event on a dry roadside segment yields 7 vests, 4 grabbers, and 28 bags. The stock gate is evaluated last of all checks: each computed line must fit within the depot's on-hand quantity for that item, or the entire issuance is refused with `ERR_SUPPLY_STOCK_EXCEEDED` — there is no partial issuance. On success the distribution is created `ISSUED` with its three issued quantities recorded, `vests_returned`, `grabbers_returned`, `lost_vests`, and `lost_grabbers` all at zero, and the depot's on-hand counts are debited.

After the event, the leader or a coordinator returns returnables by submitting `returned_vests` and `returned_grabbers` — both required, each a non-negative integer — optionally with `mark_remaining_lost`. A distribution already `RECONCILED` refuses further returns with `ERR_SUPPLY_ALREADY_RECONCILED`, and any return that would push the cumulative returned count for an item above its issued count is rejected with `ERR_RETURN_EXCEEDS_ISSUED`. Accepted returns restock the depot's `vests_on_hand` and `grabbers_on_hand` by the returned counts; every accepted return call refreshes the depot's `version` and `updated_at`, even when no units move. What happens next depends on the balance: if outstanding units remain and `mark_remaining_lost` was not set, the distribution moves from `ISSUED` to `PARTIALLY_RETURNED` (or stays `PARTIALLY_RETURNED` across successive partial returns); if the return completes the full balance, the distribution moves to `RECONCILED`. When `mark_remaining_lost` is set, the outstanding balance is written off rather than restocked — the distribution's `lost_vests` and `lost_grabbers` are set to the outstanding counts, the depot's `lost_vests_total` and `lost_grabbers_total` grow by those amounts — and the distribution moves straight to `RECONCILED`. System cascades (event cancellation, no-show, agreement suspension, agreement termination) always take the gentle path: outstanding returnables are treated as returned, restocked, and zero loss is recorded. Every path leaves the conservation invariant of §2.7 intact. Distribution listings filter by `event_id`, `depot_id`, and `status`.

### 3.6. Debris Reporting, Event Completion, and Standing

Once the event day arrives, the group has from the `scheduled_date` through 30 days after it — both endpoints included — to file the debris report; outside that window the submission is refused with `ERR_REPORT_WINDOW_CLOSED`. The event must be in `BRIEFING_DONE`, else `ERR_EVENT_NOT_BRIEFED`, and because completion moves the event out of `BRIEFING_DONE`, that single state guard also enforces the rule of at most one debris report per event. Reading the event's report collection therefore yields an array of zero or one entries.

The filing names a `weight_method` of `MEASURED` or `ESTIMATED`, plus a non-empty `material_lines` array. Each line names a `material_type` — one of `GENERAL_TRASH`, `RECYCLABLES`, `METALS`, `YARD_WASTE`, or `OTHER`, each material appearing at most once per report — and carries either a `bag_count` or a `line_weight_lbs` depending on the method; `bag_count` must be a non-negative integer and `line_weight_lbs` a non-negative number. Under `MEASURED`, the crew weighed the debris on a scale: `measured_total_weight_lbs` is required (and it is forbidden under `ESTIMATED`), each line supplies its `line_weight_lbs`; each supplied line weight is rounded half-up to one decimal place, the rounded lines are summed, and that sum must equal the measured total itself rounded half-up to one decimal place — any discrepancy is rejected with `ERR_WEIGHT_MISMATCH`. The official weight is the scale reading at one decimal place. Under `ESTIMATED`, no scale was available, so each line's weight is its `bag_count` multiplied by the per-bag average for its material — 12.75 pounds for `GENERAL_TRASH`, 7.25 for `RECYCLABLES`, 22.4 for `METALS`, 10.6 for `YARD_WASTE`, and 9.85 for `OTHER` — with each line rounded half-up to one decimal place first and the rounded lines then summed into `official_weight_lbs`. The two methods legitimately produce different official weights for the same physical cleanup. Either way, the server normalizes the lines into `material_breakdown`, a list of material and one-decimal line weight pairs, and the report — immutable once filed, per §2.4 — is created with a 201. The report object carries the `event_id`, echoes the submitted `weight_method` and `material_lines`, stores `measured_total_weight_lbs` as the one-decimal scale reading under `MEASURED` and null under `ESTIMATED`, and adds the normalized `material_breakdown` and `official_weight_lbs`.

Filing the report fires the completion cascade. The event moves to `COMPLETED` and its `completed_weight_lbs` is set to the report's `official_weight_lbs`; the two are reconciled against each other on every read of the event. The parent agreement's `cleanups_completed_in_window` and `standing` are then recomputed under the rolling measure of §2.6. And if the agreement was `SUSPENDED` and the recomputed standing is `COMPLIANT` — three or more completions now inside the window — the agreement lifts itself back to `ACTIVE` with `suspension_reason` cleared, an automatic reinstatement that increments the agreement's `version` just as a coordinator action would.

### 3.7. Hazard Discovery and Agency Escalation

When a volunteer or coordinator finds something no volunteer should handle — a `hazard_type` of `CHEMICAL_CONTAINER`, `SYRINGES`, `PROPANE_TANK`, `ASBESTOS`, or `OTHER` — the protocol is strict: do not touch the item, mark the location, and file a report. Either role may file, supplying the `segment_id` where the item lies, an optional `event_id` when the discovery happened during a scheduled event, a `description` of what was found, and a `location_note` precise enough for the agency crew to find it again. The report enters as `REPORTED`.

An open hazard — one in `REPORTED` or `ACKNOWLEDGED` — casts a shadow over its segment: scheduling any new cleanup event there is refused with `ERR_HAZARD_UNRESOLVED`, and, as §3.8 describes, an open hazard also blocks renewal approval. Clearing the shadow is the coordinator's two-step desk process. Acknowledgement, valid only from `REPORTED` (anything else draws `ERR_HAZARD_NOT_REPORTED`), mints the `agency_reference` notification reference — `AGY-` followed by twelve uppercase hexadecimal characters — the moment the responsible agency is formally notified, stamps `acknowledged_at` with the logical clock, and moves the report to `ACKNOWLEDGED`. Resolution, valid only from `ACKNOWLEDGED` (else `ERR_HAZARD_NOT_ACKNOWLEDGED`), stores the supplied `resolution_note` describing the removal or disposal, stamps `resolved_at`, and moves the report to its terminal `RESOLVED` state. Hazard listings filter by `segment_id`, `event_id`, and `status`.

### 3.8. Recognition Signs, Renewal, and End of Term

The program's public face is the recognition sign. The owning leader requests one under an `ACTIVE` agreement — a request under any other status fails with `ERR_AGREEMENT_NOT_ACTIVE` — supplying the `sign_text`, between 1 and 60 characters, that will be displayed. An agreement may have at most one live sign, where live means `REQUESTED` or `INSTALLED`; a second request while one is live is refused with `ERR_SIGN_ALREADY_EXISTS`. New signs start in `REQUESTED`.

Installation is the coordinator's job and is deliberately earned: the sign must be `REQUESTED` (else `ERR_SIGN_NOT_REQUESTED`), the agreement must be `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`), and at least one cleanup event under the agreement must have reached `COMPLETED` — installing before the group's first completed cleanup is rejected with `ERR_NO_COMPLETED_CLEANUP`. Installation stamps `installed_date` with the clock date and moves the sign to `INSTALLED`. Signs do not outlive their agreements: when an agreement is terminated, expires, or has its renewal denied, an `INSTALLED` sign moves to its terminal `REMOVED` state by cascade. An agreement's signs can be listed at any time.

Renewal keeps a successful adoption running. The owning leader may request it only from `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`) and only inside the renewal window — from 90 days before `term_end_date` through the term end date itself, both endpoints included; outside that window the request is refused with `ERR_RENEWAL_WINDOW_CLOSED`. A valid request moves the agreement to `RENEWAL_REVIEW`. The coordinator then records a `decision` of `APPROVE` or `DENY`, with an optional `note`; the decision is only meaningful from `RENEWAL_REVIEW`, else `ERR_AGREEMENT_NOT_IN_RENEWAL`. Approval is gated by the anniversary measure of §2.6 together with the segment's hazard record: every 12-month term window must hold at least three `COMPLETED` cleanups, and no hazard report on the segment may sit in `REPORTED` or `ACKNOWLEDGED` — failing either condition draws `ERR_RENEWAL_NOT_ELIGIBLE`. An approved renewal rolls the term forward: `term_start_date` becomes the old `term_end_date`, `term_end_date` becomes the new start plus 24 months, `renewal_count` increments, `standing` resets to `NOT_EVALUATED`, and the rolling window counter is recomputed, returning the agreement to `ACTIVE`. Denial moves the agreement to `EXPIRED`, returns the segment to `AVAILABLE`, and removes any installed sign.

Agreements that simply run out their clock meet the same end without a decision: when a clock advance carries the date past an `ACTIVE` agreement's `term_end_date`, the expiry sweep moves the agreement to `EXPIRED`, frees the segment to `AVAILABLE`, and removes any installed sign.

Program-wide health is a computed read rather than a stored record. The metrics view reports `active_agreements` — the count of agreements currently `ACTIVE`; `adopted_miles` and `available_miles` — the summed `mile_length` of segments in `ADOPTED` and `AVAILABLE` respectively, each rounded half-up to two decimal places; `total_debris_lbs` — the sum of `official_weight_lbs` across all debris reports at one decimal place, stable because reports are immutable; `completed_cleanups` — the count of events in `COMPLETED`; and `open_hazards` — the count of hazard reports in `REPORTED` or `ACKNOWLEDGED`.

## 4. Endpoint Definitions

Operations that create a new resource — registering a group, mapping a segment, filing an application, scheduling an event, submitting a debris report, issuing supplies, creating a depot, registering a waiver, filing a hazard report, or requesting a sign — return a `201 Created` status code. Operations that modify an existing resource in place, record a decision or lifecycle transition, or perform a read return a `200 OK` status code. Unless otherwise noted, creation and modification responses return the created or updated resource in the envelope's `data` field.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/program/groups` | Register an adopter group; the returned `id` becomes the leader's `X-User-ID` | GroupLeader |
| GET | `/program/groups/{id}` | Fetch one adopter group | ProgramCoordinator, GroupLeader |
| POST | `/program/segments` | Create an adoptable road or river segment | ProgramCoordinator |
| GET | `/program/segments/{id}` | Fetch one segment | ProgramCoordinator, GroupLeader |
| GET | `/program/segments` | List segments, filterable by `status` and `water_adjacent` | ProgramCoordinator, GroupLeader |
| POST | `/program/agreements` | Apply to adopt a segment, creating a `PENDING_REVIEW` agreement | GroupLeader |
| GET | `/program/agreements/{id}` | Fetch one agreement | ProgramCoordinator, GroupLeader |
| GET | `/program/agreements` | List agreements, filterable by `group_id`, `segment_id`, and `status` | ProgramCoordinator, GroupLeader |
| POST | `/program/agreements/{id}/review-decision` | Approve or reject a `PENDING_REVIEW` agreement | ProgramCoordinator |
| PATCH | `/program/agreements/{id}` | Amend agreement contact details under the OCC guard | ProgramCoordinator, GroupLeader |
| POST | `/program/agreements/{id}/suspend` | Suspend an `ACTIVE` agreement with the event/supply cascade | ProgramCoordinator |
| POST | `/program/agreements/{id}/terminate` | Terminate an agreement with the full cascade | ProgramCoordinator, GroupLeader |
| POST | `/program/agreements/{id}/renewal-request` | Request re-adoption renewal inside the renewal window | GroupLeader |
| POST | `/program/agreements/{id}/renewal-decision` | Approve (roll the term forward) or deny (expire) a renewal | ProgramCoordinator |
| POST | `/program/events` | Schedule a cleanup event under an `ACTIVE` agreement | GroupLeader |
| GET | `/program/events/{id}` | Fetch one event | ProgramCoordinator, GroupLeader |
| GET | `/program/events` | List events, filterable by `agreement_id` and `status` | ProgramCoordinator, GroupLeader |
| PATCH | `/program/events/{id}` | Edit headcount or date while `SCHEDULED`; edit or reschedule while `POSTPONED` | GroupLeader |
| POST | `/program/events/{id}/briefing` | Record the safety briefing and its attendee waiver list | GroupLeader |
| POST | `/program/events/{id}/postpone` | Postpone an event; the briefing must be redone after rescheduling | GroupLeader |
| POST | `/program/events/{id}/cancel` | Cancel a non-terminal event; supplies auto-reconcile and restock | ProgramCoordinator, GroupLeader |
| POST | `/program/events/{id}/debris-report` | File the debris weight and material report, completing the event | GroupLeader |
| GET | `/program/events/{id}/debris-reports` | List the event's debris report (an array of zero or one) | ProgramCoordinator, GroupLeader |
| POST | `/program/events/{id}/supplies` | Issue the computed supply allocation for an event from a depot | GroupLeader |
| GET | `/program/supplies` | List supply distributions, filterable by `event_id`, `depot_id`, and `status` | ProgramCoordinator, GroupLeader |
| GET | `/program/supplies/{id}` | Fetch one supply distribution | ProgramCoordinator, GroupLeader |
| POST | `/program/supplies/{id}/return` | Return returnables; optionally write off the remainder as lost | ProgramCoordinator, GroupLeader |
| POST | `/program/depots` | Create a supply depot with initial stock; pool totals pinned | ProgramCoordinator |
| GET | `/program/depots/{id}` | Fetch one depot with current on-hand and loss totals | ProgramCoordinator, GroupLeader |
| POST | `/program/waivers` | Register a volunteer waiver; minors need guardian consent and a supervisor | GroupLeader |
| GET | `/program/waivers/{id}` | Fetch one waiver | ProgramCoordinator, GroupLeader |
| GET | `/program/waivers` | List waivers, filterable by `agreement_id`, `supervisor_waiver_id`, and `status` | ProgramCoordinator, GroupLeader |
| POST | `/program/waivers/{id}/revoke` | Revoke an `ACTIVE` waiver | GroupLeader |
| POST | `/program/hazards` | Report a hazardous item discovery under the do-not-touch protocol | ProgramCoordinator, GroupLeader |
| GET | `/program/hazards/{id}` | Fetch one hazard report | ProgramCoordinator, GroupLeader |
| GET | `/program/hazards` | List hazard reports, filterable by `segment_id`, `event_id`, and `status` | ProgramCoordinator, GroupLeader |
| POST | `/program/hazards/{id}/acknowledge` | Acknowledge a hazard and log the agency notification reference | ProgramCoordinator |
| POST | `/program/hazards/{id}/resolve` | Mark a hazard removed or remediated | ProgramCoordinator |
| POST | `/program/agreements/{id}/signs` | Request a recognition sign for the adopting group | GroupLeader |
| GET | `/program/agreements/{id}/signs` | List an agreement's recognition signs | ProgramCoordinator, GroupLeader |
| POST | `/program/signs/{id}/install` | Install a requested sign once the agreement qualifies | ProgramCoordinator |
| GET | `/program/metrics` | Program-wide computed metrics (agreements, miles, debris, cleanups, hazards) | ProgramCoordinator, GroupLeader |
| POST | `/_clock/set_current_utc` | Advance the logical clock and run the scheduled sweeps | ProgramCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_SEGMENT_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_WAIVER_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPLY_NOT_FOUND` | 404 Not Found |
| `ERR_DEPOT_NOT_FOUND` | 404 Not Found |
| `ERR_HAZARD_NOT_FOUND` | 404 Not Found |
| `ERR_SIGN_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_PENDING` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_IN_RENEWAL` | 409 Conflict |
| `ERR_AGREEMENT_TERMINAL` | 409 Conflict |
| `ERR_EVENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_EVENT_TERMINAL` | 409 Conflict |
| `ERR_EVENT_NOT_BRIEFED` | 409 Conflict |
| `ERR_HAZARD_NOT_REPORTED` | 409 Conflict |
| `ERR_HAZARD_NOT_ACKNOWLEDGED` | 409 Conflict |
| `ERR_SIGN_NOT_REQUESTED` | 409 Conflict |
| `ERR_WAIVER_NOT_ACTIVE` | 409 Conflict |
| `ERR_SUPPLY_ALREADY_RECONCILED` | 409 Conflict |
| `ERR_HAZARD_UNRESOLVED` | 422 Unprocessable Entity |
| `ERR_MINOR_GUARDIAN_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SUPERVISOR_INVALID` | 422 Unprocessable Entity |
| `ERR_WAIVER_INVALID_ATTENDEE` | 422 Unprocessable Entity |
| `ERR_SUPERVISOR_ABSENT` | 422 Unprocessable Entity |
| `ERR_EVENT_TOO_SOON` | 422 Unprocessable Entity |
| `ERR_REPORT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_RENEWAL_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_SEGMENT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_EVENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_WEIGHT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RETURN_EXCEEDS_ISSUED` | 422 Unprocessable Entity |
| `ERR_SUPPLY_ALREADY_ISSUED` | 409 Conflict |
| `ERR_RENEWAL_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_SIGN_ALREADY_EXISTS` | 409 Conflict |
| `ERR_NO_COMPLETED_CLEANUP` | 422 Unprocessable Entity |
| `ERR_SUPPLY_STOCK_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
