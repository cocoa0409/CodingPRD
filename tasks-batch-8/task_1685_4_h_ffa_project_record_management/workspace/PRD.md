# FFA 4-H Project Records API — Product Requirements Document

## 1. Introduction

County extension programs live and die by their record books. Every program year, youth members across 4-H clubs and FFA chapters carry livestock and non-livestock projects, log every dollar and hour against them, and present that documentary trail for advisor review before anyone is allowed near a show ring. This document specifies the FFA 4-H Project Records API: a single backend service that administers club setup and club treasuries, adult volunteer screening, member enrollment and lifecycle, project and animal-tag tracking, record book submission and scoring, club meetings and attendance, county and state fair entries with stall assignments, and the award and scholarship pipeline that caps the season.

Two forces shape the design. First, the program runs on segregation of duties: the volunteer who nominates a member for an award may not endorse that same nomination, the advisor who reviews a record book may not be the member's parent or guardian, and only screened, cleared volunteers may approve the documents everything else depends on. Second, nearly every downstream privilege — confirming a fair entry, nominating a star award, granting a scholarship — is gated on a small set of computed postures and scores rather than on ad-hoc judgment, so the API derives those aggregates deterministically from ledger entries, attendance rows, and tagging records. All time-sensitive rules are evaluated against a program-year logical clock so that deadlines land identically for every club in the county.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly three roles: `ProgramAdmin`, `Volunteer`, and `Member`. A request that is missing either header, or whose `X-User-Role` value is not one of the three recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting Volunteer; ownership checks on any resource that references a Volunteer compare the resource's foreign-key field to `X-User-ID`, and segregation-of-duties checks compare it against recorded actor fields such as `nominated_by`. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting Member, and member-scoped operations require the acting member to own the target resource; a caller whose `X-User-ID` does not resolve to an existing entity of the role's backing type, or who does not own the target resource on an ownership-scoped endpoint, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The division of labor is deliberate. A `ProgramAdmin` is the county extension administrator: only this role creates clubs, registers and screens volunteers, records screening events, manages rooms and pens, and drives the logical clock. A `Volunteer` is a cleared adult leader or advisor who runs the season: enrolling and lifecycle-managing members, reviewing record books, scheduling meetings and recording attendance, confirming fair entries, assigning stalls, working the award pipeline, posting treasury transactions, and verifying animal tags. A `Member` is a youth participant who manages their own projects, record books and ledger lines, fair entries, and award and scholarship applications.

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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Version Semantics

Every resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the resource was created. Clubs, volunteers, members, projects, animal tags, record books, meetings, rooms, fair entries, stall assignments, pens, award applications, and scholarship applications additionally carry `updated_at`, refreshed to the mutation time on every change, and an integer `version` that increments by exactly one on every mutation, including state transitions and derived-field recomputation.

Four record types are immutable audit lines and carry only `id` and `created_at`: ledger entries, attendance rows, screening events, and treasury transactions. For these four, both `updated_at` and `version` are absent, even though some of their status fields do change over their lifetime.

Hierarchical consistency follows from the same principle: when a single operation mutates more than one entity — a suspension dropping a member's projects, a star nomination advancing a club counter, a reimbursement approval moving club funds — every cascade specified in §3 is applied as part of that operation, and each mutated entity's own `version` and `updated_at` advance accordingly.

### 2.5. The Program-Year Logical Clock

All deadline arithmetic and all system-stamped timestamps in the system are driven by a server-side logical clock, never by wall-clock time. Before any operator intervention, the logical clock reads 2026-08-01T00:00:00Z, and the server never falls back to wall-clock time on its own. A `ProgramAdmin`-only test-driving capability advances the logical clock to a supplied instant; the request carries `to_iso8601`, and the response echoes the new `current_utc`. The logical clock is what stamps `submitted_at` when a record book is submitted and `tagged_at` when an animal is tagged, and it anchors every deadline computation described in §3.

### 2.6. Numeric Precision and Rounding Conventions

Scores and percentages are carried to exactly two decimal places using round-half-up; this applies to a record book's `provisional_score` and `final_score`, to an award application's `rubric_score`, and to the attendance percentage that feeds a member's `eligibility_posture`. Whole-day counts (`late_days`, `ownership_days_at_entry`), the volunteer `screening_score`, and `scholarship_points` are integers. Scholarship points obey a pinned rounding order: each per-project value is rounded half-up to a whole number first, and only then are the per-line values summed — summing raw values and rounding once at the end is a rejected alternative that produces a different total. Monetary amounts are represented as integer cents throughout (`amount_cents` on ledger and treasury lines, `treasury_balance_cents` on a club).

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both treat their version field as a non-optional input.

Submitting a record book requires the client to send `expected_record_book_version`, carrying the record book's `version` as the client last observed it. If the book's current version has advanced since that observation — because another writer resubmitted the book or a review action moved it — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently building on a state the client never saw.

Nominating an award application requires the client to send `expected_club_version`, matching the current `version` of the nominee member's club. Because a STAR-track nomination consumes one of the club's two star-nomination slots, a club version that has advanced since the client last read it means the quota picture the client acted on is out of date; the nomination is rejected with `ERR_STALE_VERSION` (HTTP 412). No endpoint other than these two accepts a version field.

### 2.8. Nested Resource Retrieval and Caller Ownership

Every identifier referenced in a request — each `id` in the URL path and every identifier carried in the body — is validated for existence in a strict left-to-right order, parent before child. The first identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404), before any later identifier or any business rule is examined. Reverse-reachability lists (the members, volunteers, meetings, and treasury transactions of a club; the projects, attendance, fair entries, award applications, and scholarship applications of a member; the animal tags and record books of a project; the ledger lines of a record book; the attendance of a meeting; the stall assignments of a pen or of a fair entry) follow the same rule for their parent identifier.

Ownership scoping sits one step later. For entity-backed roles, `X-User-ID` must resolve to an existing entity of that role's backing type, and on member-scoped endpoints the acting member must own the target resource: a member may only start, drop, submit, void, enter, or withdraw records that belong to their own membership. Breaches are rejected with `ERR_FORBIDDEN` (HTTP 403).

### 2.9. Validation Priority Order

Every request passes through a fixed validation pipeline, and the first failing check determines the error returned. The order is:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is recognized; otherwise `ERR_UNAUTHENTICATED`. Applies to all endpoints.
2. **Authorization** — the acting role is permitted to invoke the endpoint; otherwise `ERR_UNAUTHORIZED`. Applies to all endpoints.
3. **Existence** — every referenced identifier exists, validated left-to-right, parent before child; otherwise `ERR_NOT_FOUND`. Applies to all endpoints.
4. **Caller ownership** — for entity-backed roles the caller resolves, and on member-scoped endpoints the acting entity owns the target; otherwise `ERR_FORBIDDEN`.
5. **State preconditions** — the target resource is in a valid from-state for the requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409). Applies to all action endpoints, so a transition attempted from the wrong state always fails here before any business check runs.
6. **Segregation of duties** — on beginning a record-book review the acting volunteer must not be the parent or guardian of the member who owns the book, and on endorsing an award application the acting volunteer must not be the volunteer who nominated it; otherwise `ERR_SEGREGATION_OF_DUTIES`.
7. **Volunteer screening gates** — approving a record book requires the acting volunteer's clearance, and clearing a volunteer requires the score and event-history preconditions of §3.2; otherwise `ERR_SCREENING_NOT_CLEARED`.
8. **Room overlap** — a new meeting must not collide with an existing one in the same room; otherwise `ERR_ROOM_CONFLICT`.
9. **Pen capacity** — a new stall assignment must not exceed the pen's aggregate capacity; otherwise `ERR_PEN_CAPACITY_EXCEEDED`.
10. **Star nomination quota** — a STAR nomination requires headroom under the club's quota; otherwise `ERR_STAR_QUOTA_EXCEEDED`.
11. **Ownership period** — confirming a fair entry requires the species ownership minimum; otherwise `ERR_OWNERSHIP_PERIOD_SHORT`.
12. **Treasury solvency** — approving a reimbursement must not drive the club treasury negative; otherwise `ERR_INSUFFICIENT_TREASURY`.
13. **Referential integrity** — cross-entity links must be consistent (project-to-member on fair entries; member and award track on scholarship applications); otherwise `ERR_REFERENTIAL_INTEGRITY`.
14. **Request shape** — required input fields are present, enum values are valid, `ends_at` is strictly after `starts_at`, and amounts are non-negative; otherwise `ERR_INVALID_REQUEST` (HTTP 400). Applies to all endpoints.
15. **Optimistic concurrency** — the `expected_..._version` field matches the parent entity's current version; otherwise `ERR_STALE_VERSION`. This is always the final gate.

## 3. Business Logic & Workflows

This section walks the program year as the county extension office lives it: clubs and their treasuries first, then the adults who must be screened before they can touch anything, then members, projects, record books, meetings, fair season, and finally awards and scholarships. Rules that guard a workflow are stated next to that workflow; §2.9 fixes the order in which they fire.

### 3.1. Club Setup and Treasury Management

A `ProgramAdmin` opens the season by creating each club with a display `name` and a two-letter `county_code`; club names are unique within their county code. A new club starts with `status` ACTIVE, `treasury_balance_cents` at zero, and `star_nomination_count` at zero. A club's `status` is either ACTIVE or SUSPENDED, and the distinction matters downstream: a member can only be activated while their club is ACTIVE. The club list can be filtered by `county_code`, and each club's members, volunteers, meetings, and treasury transactions are listable as nested collections. The `star_nomination_count` field tracks the club's STAR-track award applications sitting in the NOMINATED or ENDORSED review stages; it is maintained event by event as nominations, awards, and withdrawals occur (§3.9), and it gates star nominations.

Club money moves through treasury transactions recorded by a `Volunteer`, each carrying a `club_id`, a `txn_kind` of DUES_PAYMENT or EXPENSE_REIMBURSEMENT, and a positive `amount_cents`. The two kinds behave differently. A dues payment is POSTED on entry and credits the club's `treasury_balance_cents` immediately. An expense reimbursement is POSTED on entry but does not touch the balance until a volunteer approves it; approval moves the transaction from POSTED to APPROVED and debits the treasury, and an approval that would drive `treasury_balance_cents` negative is rejected with `ERR_INSUFFICIENT_TREASURY` (HTTP 422). A transaction still in POSTED status may be voided by a volunteer, moving it to VOIDED; voiding a dues payment reverses the credit it applied, debiting the treasury by the same amount. Both approvals and voids increment the club's `version`. At all times, `treasury_balance_cents` equals the sum of POSTED dues payments minus the sum of APPROVED reimbursements for that club. The `txn_status` lifecycle is the only mutation a treasury transaction ever undergoes; consistent with §2.4, the transaction itself carries no `version`.

### 3.2. Volunteer Registration and Screening Clearance

Before an adult can lead anything, a `ProgramAdmin` registers them as a volunteer with a `full_name`, an `email` that is unique across all volunteers, a `base_clearance` between 0 and 100 assigned by the screening committee, an optional `risk_flags` count of open background-check flags (defaulting to 0), an optional `years_service` count of completed service years (defaulting to 0), and the affiliated `club_id`. Registration computes the volunteer's initial `screening_score` and sets `screening_status` to PENDING.

The screening score is computed in a fixed three-step order, and the order matters because the cap on credited service never depends on the score itself. First, the service cap is the `base_clearance` divided by ten, rounded down to a whole number. Second, the effective service is the lesser of `years_service` and that cap. Third, the `screening_score` is the `base_clearance`, minus ten points for each open risk flag, plus two points for each effective service year. The score is an integer. It is recomputed on the same three inputs every time a screening event is recorded, and each recomputation increments the volunteer's `version`.

Screening events are the evidentiary trail: a `ProgramAdmin` records each one with a `volunteer_id`, an `event_kind` of BACKGROUND_CHECK, REFERENCE_CHECK, or INTERVIEW, and an `outcome` of PASS, FLAG, or FAIL. The events for a volunteer are listable as a nested collection.

Clearance and denial are `ProgramAdmin` decisions taken from PENDING, and both states are terminal. Clearing a volunteer (PENDING → CLEARED) requires a `screening_score` of at least 40 and no screening event on record with outcome FAIL; a clearance request that finds the score below 40 or a FAIL event in the history is rejected with `ERR_SCREENING_NOT_CLEARED` (HTTP 422). Denying a volunteer (PENDING → DENIED) has no further preconditions. Clearance is not merely ceremonial: only a volunteer whose `screening_status` is CLEARED may approve a record book (§3.5).

### 3.3. Member Enrollment and Lifecycle

A `Volunteer` or `ProgramAdmin` enrolls a youth member with a `full_name`, a `birth_date` (an ISO 8601 calendar date used to derive the member's age division), the home `club_id`, and an optional `is_club_officer` flag that defaults to false and later feeds the leadership bonus in record-book scoring (§3.5). A new member starts with `enrollment_status` ENROLLED and an `eligibility_posture` of INELIGIBLE.

From there the member lifecycle is driven entirely by volunteers. Activation moves ENROLLED → ACTIVE, requires the member's club to be ACTIVE, and recomputes the member's `eligibility_posture`. Suspension moves ACTIVE → SUSPENDED and is the system's big eraser: it forces the member's `eligibility_posture` to INELIGIBLE and drops every project of the member that is still PLANNED or ACTIVE, moving each to DROPPED. Reinstatement moves SUSPENDED → ACTIVE and recomputes the posture from current evidence. Graduation moves ACTIVE → GRADUATED, is terminal, and requires that the member holds no fair entry still in ENTERED or CONFIRMED status; it likewise forces the posture to INELIGIBLE. Each of these transitions increments the member's `version`, and any transition attempted from a state other than its declared from-state is rejected with `ERR_INVALID_STATE` (HTTP 409) — here and everywhere else in this section.

### 3.4. Projects and Livestock Tagging

A project binds a member to one category of work for a program year. It is created — by the member themselves or by a volunteer — with a `member_id`, a `project_type` of BEEF, SHEEP, SWINE, CROPS, FOODS, or ROBOTICS, and a `program_year` such as 2026; it starts in PLANNED status with `grade` NONE. The member starts their own project (PLANNED → ACTIVE), which requires the member's `enrollment_status` to be ACTIVE.

Completion is a volunteer's judgment call with documentary backing: completing a project (ACTIVE → COMPLETED) requires that a record book exists for the project in APPROVED status, and the volunteer supplies a `grade` of A, B, or C, which is stored on the project and later feeds scholarship points (§3.9); completion recomputes the member's posture. Dropping is the member's own act, available from PLANNED or from ACTIVE, and moves the project to DROPPED. Dropping an ACTIVE project also rejects its record book if that book is still in flight — a book in DRAFT, SUBMITTED, UNDER_REVIEW, or RETURNED moves to REJECTED — while a book already APPROVED or REJECTED is untouched.

Livestock projects carry an additional evidentiary burden: the animals themselves must be tagged and verified. Tagging an animal — by the member or a volunteer — records the `project_id`, the official ear-tag `tag_number` (unique per program year), the `species` (BEEF, SHEEP, or SWINE), and `owned_since`, the UTC timestamp at which ownership began; the server stamps `tagged_at` from the logical clock, and the record starts with `tagging_status` TAGGED. A volunteer then verifies the tag (TAGGED → VERIFIED) or rejects it (TAGGED → REJECTED); either decision recomputes the owning member's `eligibility_posture`, since verified tags are one leg of the eligibility stool (§3.7).

### 3.5. Record Books: Ledgering, Submission, and Review

The record book is the spine of the whole program. A member opens one for a project with a `project_id` and a `program_year`; it starts in DRAFT status, with `submitted_at` empty and `late_days` at zero.

While the book is in DRAFT — and again after a return — the member accumulates ledger lines against it. Each line carries the `record_book_id`, an `entry_kind` of EXPENSE, INCOME, or HOURS, an `amount_cents` value holding the monetary amount in cents for EXPENSE and INCOME lines and zero for HOURS lines, an `hours` value holding time worked for HOURS lines and zero for monetary lines, and the `recorded_on` calendar date of the activity. Each line's `entry_status` is POSTED on creation. A member may void a posted line (`entry_status` POSTED → VOIDED) only while its record book is still in DRAFT or RETURNED; once the book is under review or beyond, the ledger is frozen. Consistent with §2.4, ledger lines are audit records and carry no `version` of their own.

Submission is the member's act and comes in two flavors that share one endpoint capability. A first submission moves DRAFT → SUBMITTED and requires that the book contains at least one POSTED ledger line and that the project is still ACTIVE. The submission payload carries the four section scores — `completeness`, `accuracy`, `financial`, and `reflection`, each from 0 to 100 — together with the OCC field `expected_record_book_version` described in §2.7. On submission the server stamps `submitted_at` from the logical clock, computes `late_days`, and computes the `provisional_score`. A book returned for revision is resubmitted the same way (RETURNED → SUBMITTED); resubmission requires only that the project is still ACTIVE, and it re-stamps `submitted_at` and recomputes both `late_days` and the `provisional_score`.

Lateness is measured against the program-year record-book deadline of July 15, 2026, end of day UTC: `late_days` counts the whole calendar dates by which the UTC date of `submitted_at` falls after that date, and is zero for a book submitted on or before it.

The two scores share one weighted core and diverge in their adjustments. The provisional score, computed at submission, is the plain weighted sum of the four section scores: `completeness` at thirty percent, `accuracy` at twenty-five percent, `financial` at twenty-five percent, and `reflection` at twenty percent — no bonus, no penalty. The final score, computed at approval, applies its adjustments in a pinned order: start from the same weighted sum; then, if the member's `is_club_officer` flag is set, add a five-point leadership bonus and cap the result at 100; then subtract the late penalty — three points per whole late day, with the penalty itself capped at fifteen points — and floor the result at zero. Both scores are rounded half-up to two decimal places.

Review belongs to volunteers and runs SUBMITTED → UNDER_REVIEW → a terminal verdict, with one return path. Beginning a review (SUBMITTED → UNDER_REVIEW) carries a segregation-of-duties guard: the acting volunteer must not be the parent or guardian of the member who owns the book, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). From UNDER_REVIEW, a volunteer may return the book for revision (→ RETURNED), reject it outright (→ REJECTED), or approve it (→ APPROVED). Approval is gated on clearance: the acting volunteer's `screening_status` must be CLEARED, otherwise the approval is rejected with `ERR_SCREENING_NOT_CLEARED` (HTTP 422). Approval computes the `final_score`, recomputes the owning member's `eligibility_posture`, and — because an APPROVED book is the precondition for project completion — it is the hinge on which the rest of the season swings. APPROVED and REJECTED are both terminal for the book.

### 3.6. Meetings, Rooms, and Attendance Tracking

Club meetings matter because attendance feeds the eligibility posture. A `ProgramAdmin` first creates rooms, each with a unique `name` and a `capacity` giving its maximum occupancy. A volunteer then schedules a meeting with a `club_id`, a `starts_at`, an `ends_at`, and a `room_id`; the meeting starts in SCHEDULED status. Two shape rules guard scheduling: `ends_at` must be strictly after `starts_at` (violations are rejected with `ERR_INVALID_REQUEST`, HTTP 400), and the room may not be double-booked — the new meeting's half-open interval, which includes its start and excludes its end, must not overlap any existing SCHEDULED or HELD meeting in the same room, on pain of `ERR_ROOM_CONFLICT` (HTTP 409). Two meetings that merely touch, one ending at exactly the instant the other begins, do not overlap and are both allowed. The meeting list supports optional `room_id` and `club_id` filters, and each meeting's attendance is listable as a nested collection.

After the fact, a volunteer marks the meeting held (SCHEDULED → HELD) or cancels it (SCHEDULED → CANCELLED); both states are terminal. Marking held is the consequential act: it recomputes the `eligibility_posture` of every ACTIVE member of the meeting's club, because attendance evidence has now landed.

Attendance itself is recorded per member per meeting by a volunteer, each row carrying the `meeting_id`, the `member_id`, and an `attendance_status` of PRESENT, ABSENT, or EXCUSED. Attendance rows are audit lines in the sense of §2.4. How the three dispositions feed the posture percentage is the subject of the next subsection.

### 3.7. The Member Eligibility Posture

A member's `eligibility_posture` — ELIGIBLE, CONDITIONAL, or INELIGIBLE — is a derived aggregate recomputed from three evidence sources: meeting attendance, record book approval, and livestock tagging. It is never set directly by a client.

The attendance component divides the count of the member's attendance rows marked PRESENT by the combined count of rows marked PRESENT or ABSENT, expressed as a percentage and rounded half-up to two decimal places; rows marked EXCUSED are excluded from both the numerator and the denominator. When a member has no PRESENT or ABSENT rows at all, the percentage is undefined and the attendance threshold is treated as not met. The two documentary components are boolean: whether any record book belonging to a project of this member has reached APPROVED, and — required only when the member carries at least one BEEF, SHEEP, or SWINE project — whether every such livestock project has at least one animal tag in VERIFIED status.

The posture is ELIGIBLE when the attendance percentage is at least 75 and both documentary conditions hold. It is CONDITIONAL when the attendance percentage is at least 75 and exactly one of the two documentary conditions holds — an approved record book without the required verified tags, or verified tags without an approved record book. It is INELIGIBLE in every other case. The threshold boundary is inclusive: an attendance percentage of exactly 75.00 satisfies it.

Recomputation is event-driven. The posture is recomputed when the member is activated or reinstated, when one of their record books is approved, when one of their projects is completed, when an animal tag on one of their livestock projects is verified or rejected, and when a meeting of their club is marked held — in that last case, for every ACTIVE member of the club. Suspension and graduation are the exceptions: they do not recompute the posture but force it directly to INELIGIBLE, and a new member always starts at INELIGIBLE.

### 3.8. Fair Entries, Ownership Windows, and Stall Assignments

Fair season begins when a member enters a project into a fair, supplying a `member_id`, a `project_id`, and a `fair_level` of COUNTY or STATE. The project must belong to the entering member; a mismatch is rejected with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422). The entry starts in ENTERED status, and at creation the system computes `ownership_days_at_entry` against the fixed program-year fair-entry deadline of 2026-08-01T00:00:00Z. The entry's primary animal is the earliest-created VERIFIED animal tag on the project, with ties broken by the smallest `created_at` and then by the smallest `tag_number` lexicographically; `ownership_days_at_entry` counts the whole days between that animal's `owned_since` and the deadline. The fair-entry list supports optional `project_id` and `member_id` filters.

Confirmation is a volunteer's act and the gateway to the grounds: confirming an entry (ENTERED → CONFIRMED) requires the member's `eligibility_posture` to be ELIGIBLE and the entry's `ownership_days_at_entry` to meet the species minimum — at least 60 days for BEEF, at least 30 days for SHEEP or SWINE, with exactly the required number of days qualifying. An entry that falls short of its species minimum is rejected with `ERR_OWNERSHIP_PERIOD_SHORT` (HTTP 422).

Once an entry is confirmed, fairground logistics take over. A `ProgramAdmin` maintains pens, each with a unique `label` and an `animal_capacity`. A volunteer assigns a stall to an entry by supplying a `fair_entry_id` and a `pen_id`; the assignment starts in ASSIGNED status and consumes one unit of the pen's capacity. The check is an aggregate count, not an interval rule: an assignment that would push the pen's count of ASSIGNED stall assignments beyond its `animal_capacity` is rejected with `ERR_PEN_CAPACITY_EXCEEDED` (HTTP 422). Releasing an assignment (ASSIGNED → RELEASED) frees one unit of capacity again, and a pen's assignments and an entry's assignments are both listable as nested collections.

The remaining entry transitions close the loop. Marking an entry exhibited (CONFIRMED → EXHIBITED, a volunteer action) requires that a stall assignment exists for the entry in ASSIGNED status. Scratching removes an entry from the fair: a member may scratch their own entry while it is ENTERED, and a volunteer may scratch a CONFIRMED entry; either path moves the entry to SCRATCHED and releases any stall assignment for the entry (ASSIGNED → RELEASED), freeing the pen capacity it held. EXHIBITED and SCRATCHED are terminal.

### 3.9. Award Applications, Star Nominations, and Scholarships

The awards pipeline runs on a strict chain of custody. A member drafts an award application with a `member_id`, an `award_track` of DEGREE, STAR, or SCHOLARSHIP, and the `record_book_id` of the record book to be evaluated; the application starts in DRAFT status. The award-application list supports optional `record_book_id` and `member_id` filters.

Nomination moves DRAFT → NOMINATED and is a volunteer's act. The linked record book must be APPROVED, and nomination is OCC-guarded on the member's club via `expected_club_version` (§2.7). For the STAR track the club quota applies: the member's club must have a `star_nomination_count` below two — two active star nominations per club is the hard ceiling — or the nomination is rejected with `ERR_STAR_QUOTA_EXCEEDED` (HTTP 422). A successful nomination records the acting volunteer's id in `nominated_by`, and for the STAR track it also increments the club's `star_nomination_count` by one and advances the club's `version`; a stale club version therefore surfaces here as `ERR_STALE_VERSION` before the quota can be consumed against out-of-date information.

Endorsement (NOMINATED → ENDORSED) must be performed by a different volunteer than the one recorded in `nominated_by`; a self-endorsement is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). Evaluation (ENDORSED → EVALUATED) takes two payload inputs — `participation_pct`, a percentage from 0 to 100, and `leadership_pts`, a non-negative integer — and computes the `rubric_score` and `award_tier`. The rubric score blends three components: one-half of the linked record book's `final_score`, three-tenths of `participation_pct`, and one-fifth of the leadership percentage, where the leadership percentage is `leadership_pts` capped at twenty points and expressed as a percentage of that cap. The result is rounded half-up to two decimal places. The tier is GOLD when the rubric score is at least 85, SILVER when at least 70, BRONZE when at least 55, and NONE below 55; boundaries are inclusive, so a score of exactly 85.00 earns GOLD.

From EVALUATED the verdict splits cleanly. Awarding (EVALUATED → AWARDED) requires an `award_tier` other than NONE, and for the STAR track it releases the club's star slot, decrementing `star_nomination_count` by one. Denying (EVALUATED → DENIED) requires the tier to be exactly NONE. A member may also withdraw their own application, from NOMINATED or from ENDORSED, moving it to WITHDRAWN; withdrawing a NOMINATED STAR application releases the club's star slot (the count decrements by one), while withdrawing an ENDORSED application simply retires the application. AWARDED, DENIED, and WITHDRAWN are terminal.

Scholarships build on top of the award pipeline. A member opens a scholarship application with a `member_id` and a `linked_award_application_id`; the linked application must belong to the same member and must be on the SCHOLARSHIP award track, otherwise creation is rejected with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422). The application starts in OPEN status, and the scholarship list supports optional `linked_award_application_id` and `member_id` filters. Submitting it (OPEN → UNDER_REVIEW) requires the linked award application to be EVALUATED with an `award_tier` of GOLD or SILVER, and computes `scholarship_points` from the member's completed projects: for each project in COMPLETED status graded A, B, or C, a base of seven points is multiplied by the grade factor — one and a half for A, one and two-tenths for B, one for C — and each per-project value is rounded half-up to a whole number first, per §2.6, before the values are summed into the total. Two completed A-grade projects, for instance, contribute eleven points each and total twenty-two. Granting (UNDER_REVIEW → GRANTED, a volunteer's act) requires `scholarship_points` of at least 30; declining (UNDER_REVIEW → DECLINED) carries no further precondition. GRANTED and DECLINED are terminal.

## 4. Endpoint Definitions

All endpoints are served under the `/api` prefix. Endpoints that create a new resource return `201 Created`; endpoints that modify an existing resource or drive a state transition return `200 OK`; reads return `200 OK`. The request and response shapes for each operation are defined by the narratives in §3 together with the envelope contract in §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |
| POST | `/api/clubs` | Create a club | ProgramAdmin |
| GET | `/api/clubs` | List clubs (paginated; optional `county_code` filter) | ProgramAdmin, Volunteer, Member |
| GET | `/api/clubs/{id}` | Fetch a club | ProgramAdmin, Volunteer, Member |
| GET | `/api/clubs/{id}/members` | List members of a club | ProgramAdmin, Volunteer, Member |
| GET | `/api/clubs/{id}/volunteers` | List volunteers of a club | ProgramAdmin, Volunteer |
| GET | `/api/clubs/{id}/meetings` | List meetings of a club | ProgramAdmin, Volunteer, Member |
| GET | `/api/clubs/{id}/treasury-transactions` | List treasury transactions of a club | ProgramAdmin, Volunteer |
| POST | `/api/volunteers` | Register a volunteer; computes initial screening score | ProgramAdmin |
| GET | `/api/volunteers/{id}` | Fetch a volunteer | ProgramAdmin, Volunteer |
| POST | `/api/volunteers/{id}/clear` | Clear a volunteer after screening | ProgramAdmin |
| POST | `/api/volunteers/{id}/deny` | Deny a volunteer | ProgramAdmin |
| GET | `/api/volunteers/{id}/screening-events` | List screening events for a volunteer | ProgramAdmin, Volunteer |
| POST | `/api/screening-events` | Record a screening event; recomputes the volunteer's screening score | ProgramAdmin |
| POST | `/api/members` | Enroll a member | Volunteer, ProgramAdmin |
| GET | `/api/members/{id}` | Fetch a member | ProgramAdmin, Volunteer, Member |
| POST | `/api/members/{id}/activate` | Activate an enrolled member | Volunteer |
| POST | `/api/members/{id}/suspend` | Suspend a member; drops non-terminal projects | Volunteer |
| POST | `/api/members/{id}/reinstate` | Reinstate a suspended member | Volunteer |
| POST | `/api/members/{id}/graduate` | Graduate a member | Volunteer |
| GET | `/api/members/{id}/projects` | List projects for a member | ProgramAdmin, Volunteer, Member |
| GET | `/api/members/{id}/attendance` | List attendance rows for a member | ProgramAdmin, Volunteer, Member |
| GET | `/api/members/{id}/fair-entries` | List fair entries for a member | ProgramAdmin, Volunteer, Member |
| GET | `/api/members/{id}/award-applications` | List award applications for a member | ProgramAdmin, Volunteer, Member |
| GET | `/api/members/{id}/scholarship-apps` | List scholarship applications for a member | ProgramAdmin, Volunteer, Member |
| POST | `/api/projects` | Create a project for a member | Member, Volunteer |
| GET | `/api/projects/{id}` | Fetch a project | ProgramAdmin, Volunteer, Member |
| POST | `/api/projects/{id}/start` | Start a planned project | Member |
| POST | `/api/projects/{id}/complete` | Complete a project with a final grade | Volunteer |
| POST | `/api/projects/{id}/drop` | Drop a project | Member |
| GET | `/api/projects/{id}/animal-tags` | List animal tags for a project | ProgramAdmin, Volunteer, Member |
| GET | `/api/projects/{id}/record-books` | List record books for a project | ProgramAdmin, Volunteer, Member |
| POST | `/api/animal-tags` | Tag an animal on a livestock project | Member, Volunteer |
| POST | `/api/animal-tags/{id}/verify` | Verify an animal tag | Volunteer |
| POST | `/api/animal-tags/{id}/reject` | Reject an animal tag | Volunteer |
| POST | `/api/record-books` | Create a record book for a project | Member |
| GET | `/api/record-books/{id}` | Fetch a record book | ProgramAdmin, Volunteer, Member |
| GET | `/api/record-books/{id}/ledger-entries` | List ledger entries for a record book | ProgramAdmin, Volunteer, Member |
| POST | `/api/ledger-entries` | Add a ledger entry to a record book | Member |
| POST | `/api/ledger-entries/{id}/void` | Void a posted ledger entry while its book is DRAFT or RETURNED | Member |
| POST | `/api/record-books/{id}/submit` | Submit or resubmit a record book (OCC-guarded) | Member |
| POST | `/api/record-books/{id}/begin-review` | Begin advisor review of a submitted record book | Volunteer |
| POST | `/api/record-books/{id}/return` | Return a record book to the member for revision | Volunteer |
| POST | `/api/record-books/{id}/approve` | Approve a record book; computes the final score | Volunteer |
| POST | `/api/record-books/{id}/reject` | Reject a record book | Volunteer |
| POST | `/api/rooms` | Create a room | ProgramAdmin |
| GET | `/api/rooms/{id}` | Fetch a room | ProgramAdmin, Volunteer |
| POST | `/api/meetings` | Schedule a meeting; enforces the room half-open overlap rule | Volunteer |
| GET | `/api/meetings` | List meetings (paginated; optional `room_id` / `club_id` filters) | ProgramAdmin, Volunteer, Member |
| GET | `/api/meetings/{id}` | Fetch a meeting | ProgramAdmin, Volunteer, Member |
| POST | `/api/meetings/{id}/mark-held` | Mark a scheduled meeting as held; recomputes member postures | Volunteer |
| POST | `/api/meetings/{id}/cancel` | Cancel a scheduled meeting | Volunteer |
| GET | `/api/meetings/{id}/attendance` | List attendance for a meeting | ProgramAdmin, Volunteer, Member |
| POST | `/api/attendance` | Record a member's attendance at a meeting | Volunteer |
| POST | `/api/pens` | Create a pen | ProgramAdmin |
| GET | `/api/pens/{id}` | Fetch a pen | ProgramAdmin, Volunteer |
| GET | `/api/pens/{id}/stall-assignments` | List stall assignments for a pen | ProgramAdmin, Volunteer |
| POST | `/api/fair-entries` | Create a fair entry; computes ownership days | Member |
| GET | `/api/fair-entries` | List fair entries (paginated; optional `project_id` / `member_id` filters) | ProgramAdmin, Volunteer, Member |
| GET | `/api/fair-entries/{id}` | Fetch a fair entry | ProgramAdmin, Volunteer, Member |
| POST | `/api/fair-entries/{id}/confirm` | Confirm a fair entry after eligibility and ownership checks | Volunteer |
| POST | `/api/fair-entries/{id}/mark-exhibited` | Mark a confirmed entry as exhibited | Volunteer |
| POST | `/api/fair-entries/{id}/scratch` | Scratch an entry; releases its stall assignment | Member, Volunteer |
| GET | `/api/fair-entries/{id}/stall-assignments` | List stall assignments for a fair entry | ProgramAdmin, Volunteer, Member |
| POST | `/api/stall-assignments` | Assign a stall pen to a confirmed fair entry | Volunteer |
| POST | `/api/stall-assignments/{id}/release` | Release a stall assignment | Volunteer |
| POST | `/api/award-applications` | Create an award application | Member |
| GET | `/api/award-applications` | List award applications (paginated; optional `record_book_id` / `member_id` filters) | ProgramAdmin, Volunteer, Member |
| GET | `/api/award-applications/{id}` | Fetch an award application | ProgramAdmin, Volunteer, Member |
| POST | `/api/award-applications/{id}/nominate` | Nominate a draft award application (OCC-guarded on the club for STAR) | Volunteer |
| POST | `/api/award-applications/{id}/endorse` | Endorse a nominated application (different volunteer than nominator) | Volunteer |
| POST | `/api/award-applications/{id}/evaluate` | Evaluate an endorsed application; computes rubric score and tier | Volunteer |
| POST | `/api/award-applications/{id}/award` | Award an evaluated application with a non-NONE tier | Volunteer |
| POST | `/api/award-applications/{id}/deny` | Deny an evaluated application with a NONE tier | Volunteer |
| POST | `/api/award-applications/{id}/withdraw` | Withdraw a nominated or endorsed application | Member |
| POST | `/api/scholarship-apps` | Create a scholarship application linked to a SCHOLARSHIP-track award application | Member |
| GET | `/api/scholarship-apps` | List scholarship applications (paginated; optional `linked_award_application_id` / `member_id` filters) | ProgramAdmin, Volunteer, Member |
| GET | `/api/scholarship-apps/{id}` | Fetch a scholarship application | ProgramAdmin, Volunteer, Member |
| POST | `/api/scholarship-apps/{id}/submit` | Submit a scholarship application; computes scholarship points | Member |
| POST | `/api/scholarship-apps/{id}/grant` | Grant a scholarship | Volunteer |
| POST | `/api/scholarship-apps/{id}/decline` | Decline a scholarship | Volunteer |
| POST | `/api/treasury-transactions` | Record a dues payment or expense reimbursement | Volunteer |
| POST | `/api/treasury-transactions/{id}/void` | Void a POSTED treasury transaction; reverses any credit it applied | Volunteer |
| GET | `/api/treasury-transactions/{id}` | Fetch a treasury transaction | ProgramAdmin, Volunteer |
| POST | `/api/treasury-transactions/{id}/approve` | Approve an expense reimbursement; debits the club treasury | Volunteer |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API can return and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3, evaluated in the priority order of §2.9.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_SCREENING_NOT_CLEARED` | 422 |
| `ERR_ROOM_CONFLICT` | 409 |
| `ERR_PEN_CAPACITY_EXCEEDED` | 422 |
| `ERR_STAR_QUOTA_EXCEEDED` | 422 |
| `ERR_OWNERSHIP_PERIOD_SHORT` | 422 |
| `ERR_INSUFFICIENT_TREASURY` | 422 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
