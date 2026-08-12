# Board Governance API — Product Requirements Document

## 1. Introduction

A corporate secretary's office runs on evidence: notices sent on time, quorum established on the record, votes tallied against the right denominator, minutes approved and entered into a tamper-evident book, and every one of those artifacts defensible years later under audit. When that administration lives in spreadsheets, shared drives, and email threads, the failure modes are quiet and expensive — a special meeting noticed under the regular-meeting rule, a conflicted director's ballot counted into a denominator, a superseded bylaws version silently governing a vote, a minute book with gaps nobody noticed until an auditor asked.

This document specifies the Board Governance API, a single system of record for board meeting and minute book administration across any number of corporations. The API covers the full governance cycle: bylaws drafting and adoption with version supersession; director appointment, independence classification, resignation, and term expiry; committee charters, membership, and rotation limits; meeting scheduling, notice, attendance, quorum, and adjournment; agenda assembly and access-controlled board packages; resolutions decided on the floor or by written consent; conflict-of-interest disclosure and recusal; and minute approval, retention, purge, and audit reconstruction. Every time-dependent rule is evaluated against a logical governance clock rather than the wall clock, so that notice windows, consent deadlines, and retention purges are deterministic and reproducible under test.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. A request missing either header, or carrying an empty value for one, is rejected with `ERR_MISSING_CONTEXT_HEADER` (HTTP 400). The platform recognizes exactly four roles, spelled as follows: `CorporateSecretary`, `Director`, `BoardChair`, and `ExternalAuditor`. Each endpoint admits a specific subset of these roles (enumerated in §4); a caller whose role is not admitted, or who fails an ownership check attached to the endpoint, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

A `CorporateSecretary` is the corporate secretary office operator and administers bylaws, the meeting calendar, board packages, minutes, and committees. A `Director` is a board member who votes, signs written consents, waives their own notice, files disclosures, and reads board packages within their clearance tier. A `BoardChair` is the presiding director of a meeting and convenes and adjourns it, opens and closes floor votes, and approves or rejects its minutes. An `ExternalAuditor` is an outside audit requester with read access plus the audit request lifecycle.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Director`, `X-User-ID` is the `id` of the acting Director; ownership checks on any resource that references a Director — waiving a notice, casting or recasting a ballot, signing a consent, filing one's own disclosure, resigning oneself — compare the resource's director foreign-key field to `X-User-ID`. When `X-User-Role` is `BoardChair`, `X-User-ID` is likewise the `id` of the acting Director, and chair-privileged actions on a meeting or its minutes compare it against the meeting's `chair_director_id`. When `X-User-Role` is `CorporateSecretary`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `ExternalAuditor`: an operator identifier with no entity backing and no ownership comparisons.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter says how many items to skip and defaults to 0. Unless a specific view states otherwise, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Governance Clock

Every time-dependent rule in this document — notice deadlines, convene eligibility, consent windows, term expiry, retention purges — is evaluated against a logical governance clock, never the host wall clock. At server startup, before any administrative action, the clock reads 2026-05-01T00:00:00Z. A `CorporateSecretary` advances it through an administrative capability (`POST /_clock/set_current_utc`) carrying a `to_iso8601` timestamp; the capability answers with the new `current_utc` and mutates no entity. Moving the clock does not, by itself, expire terms, lapse consents, or purge minutes: those time-driven rules are applied only when the governance checkpoint described in §3.9 is run explicitly.

### 2.5. Common Resource Properties

Every resource type in the API — Corporation, Bylaws, Director, Committee, CommitteeMembership, Meeting, MeetingNotice, AgendaItem, BoardPackage, PackageDocument, AttendanceRecord, Resolution, VoteRecord, ConflictDisclosure, Minutes, and AuditRequest — carries the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every change to the resource.
- `version` (integer): a system-managed counter that increments with every mutation of the resource.

The three-fractional-digit ISO 8601 UTC format is not limited to these two fields: every timestamp the server emits in a response body — lifecycle stamps such as `sent_at`, `deadline_at`, `waived_at`, `convened_at`, `recorded_at`, `sealed_at`, `distributed_at`, `cast_at`, `closed_at`, `adopted_at`, `cleared_at`, `approved_at`, derived instants such as `retention_until` and `consent_deadline_at`, the clock capability's `current_utc`, and the reconstruction log's `occurred_at` — is serialized in that same format (for example, `2026-06-10T10:00:00.000Z`). Per §2.8, timestamps are nonetheless compared at second precision, so the fractional digits carry no semantic weight.

The mutation rule is deliberately broad: direct edits, lifecycle transitions, recomputed counters and flags, and cascade-driven changes all refresh `updated_at` and increment `version` on each resource they touch. A corporation is created with `version` at 1.

### 2.6. The Bylaws Rulebook and Snapshot Pinning

Each corporation is governed at any moment by at most one ADOPTED bylaws set, pointed to by the corporation's `current_bylaws_id`. Successive drafts of a corporation's bylaws are numbered by a per-corporation monotonic `version_no`, and supersession is recorded as a chain: a bylaws displaced by a newer adoption keeps a `superseded_by_id` reference to its successor, along with the `adopted_at` timestamp it earned when it was in force.

Because governance rules change when bylaws change, several artifacts pin the bylaws version they were created under rather than consulting whatever happens to be current later. A meeting remembers the bylaws in force when its notices were sent via `bylaws_id_at_notice`, and its notice deadlines and quorum arithmetic are answered from that pinned set. A written consent pins `consent_bylaws_id` at circulation and computes its signature requirement from that set. A minutes record's retention window is computed from the bylaws in force at approval time. Pinning is one-directional: repointing a corporation's rulebook never rewrites an artifact that was pinned earlier.

### 2.7. Optimistic Concurrency Control

Two write operations in the API are guarded by optimistic concurrency control, and each takes a mandatory expected-version field.

Adopting a bylaws supersedes the corporation's currently adopted rulebook, so an adoption request must carry `expected_corporation_version` equal to the corporation's current `version` as the client last observed it. If the corporation's version has advanced beyond the supplied value — for example because an earlier adoption already repointed the rulebook — the request is rejected as stale with `ERR_STALE_VERSION` (HTTP 412): the client based its adoption on a superseded view of the corporation.

Rescheduling a meeting rewrites its calendar window and deletes notices already issued, so a reschedule request must carry `expected_meeting_version` equal to the meeting's current `version` as the client last observed it. If the meeting's version has advanced beyond the supplied value, the request is rejected as stale with `ERR_STALE_MEETING_VERSION` (HTTP 412): the client based its new window on a superseded view of the meeting.

No other endpoint accepts or requires a version field.

### 2.8. Precision, Rounding, and Interval Semantics

Numeric rules in the API obey fixed precision contracts. Head-count arithmetic — quorum sizes, consent requirements, vote tallies — is performed in integers; where a percentage of a headcount is needed, the ceiling of the percentage product is taken first and only then compared against any absolute floor, and where a majority threshold is needed, an integer floor of half the pool plus one is used. Tenure calculations are carried in years to exactly two decimal places, rounded half up before any comparison against a limit. Governance approval percentages are expressed with exactly one decimal place, rounded half up, and the rounding is applied to each resolution's percentage before any averaging. All timestamps are compared at second precision. Content hashes and reconstruction digests are SHA-256 values rendered as lowercase hexadecimal.

Interval semantics differ by domain and are not interchangeable. Meeting calendar windows and director or membership terms are half-open: the start instant is included, the end instant is excluded, so two meetings scheduled back to back — one ending exactly when the next begins — do not conflict. Conflict disclosure windows are closed intervals with both ends inclusive, so a new disclosure that merely touches an existing one at an endpoint does conflict.

### 2.9. Single-Corporation Referential Integrity

All collections in the API are flat, root-level resources; a corporation's scope is expressed through the `corporation_id` carried on its bylaws, directors, committees, meetings, resolutions, disclosures, minutes, and audit requests rather than through nested URLs. Every identifier supplied in a request — whether a path `id` or a body reference such as `director_id`, `committee_id`, `meeting_id`, `resolution_id`, `package_id`, `chair_director_id`, `proxy_holder_director_id`, `proposed_by_director_id`, or `clearing_resolution_id` — must resolve to a row that exists, and every cross-reference inside one payload must stay within a single corporation. A payload that points a corporation's resource at another corporation's director, committee, meeting, or resolution is rejected with `ERR_CROSS_CORPORATION_REFERENCE` (HTTP 422).

### 2.10. Cascading Consistency Across the Governance Graph

State changes in one resource frequently force reconciliation in others, and the server performs those reconciliations as part of the same operation rather than leaving them to clients. A director who resigns or whose term expires takes all of that director's committee memberships down with them, and each affected committee re-evaluates its chair occupancy and quorum posture on the spot. Dissolving a committee ends every active membership in it. Cancelling a meeting drops its agenda, returns its in-flight resolutions to draft, voids their ballots, and withdraws any package not yet distributed. Re-tabling or redrafting a resolution voids its outstanding ballots. Purging minutes erases their body while preserving their fingerprint. Each resource mutated by such a cascade — parent or child — is independently updated per §2.5: its `updated_at` is refreshed and its `version` is incremented.

### 2.11. Validation Priority Order

When several rules could reject the same request, the server evaluates them in a fixed priority order and reports the first failure, so the error a client receives is deterministic. The tiers, from first to last, are:

1. **Context headers** — presence of `X-User-ID` and `X-User-Role` (`ERR_MISSING_CONTEXT_HEADER`).
2. **Role and ownership** — the caller's role is admitted to the endpoint, and self-scoped or chair-scoped identity checks hold (`ERR_FORBIDDEN_ROLE`).
3. **Schema** — required fields are present and well-formed, enum fields carry declared members, and date ranges within a body are internally consistent: a `term_end` strictly after its `term_start`, an `effective_to` on or after its `effective_from`, a `scope_end` on or after its `scope_start` (`ERR_VALIDATION`).
4. **Existence** — every identifier in the path and every referenced id in the body resolves to an existing row (`ERR_NOT_FOUND`).
5. **State** — the target resource stands in a source state of the requested transition (`ERR_INVALID_STATE_TRANSITION`).
6. **Clock-relative temporal rules** — future-dated scheduling (`ERR_SCHEDULED_START_IN_PAST`), convene no earlier than the scheduled start (`ERR_MEETING_NOT_YET`), distribution inside the package lead window (`ERR_PACKAGE_DISTRIBUTION_LATE`), and consent signing before the deadline (`ERR_CONSENT_DEADLINE_PASSED`); this tier guards meeting creation and rescheduling, convening, package distribution, and vote casting.
7. **Compliance rules** — recusal obligations (`ERR_CONFLICT_RECUSAL_REQUIRED`), audit-committee independence (`ERR_AUDIT_COMMITTEE_INDEPENDENCE`), and document tier clearance (`ERR_PACKAGE_ACCESS_DENIED`); this tier guards ballot and consent signing, membership adds, and single-document reads.
8. **Uniqueness, overlap, and capacity constraints** — calendar overlap (`ERR_MEETING_TIME_CONFLICT`), disclosure window overlap (`ERR_DISCLOSURE_WINDOW_CONFLICT`), seat capacity (`ERR_SEAT_CAPACITY_EXCEEDED`), duplicate ballots (`ERR_DUPLICATE_VOTE`), duplicate attendance (`ERR_DUPLICATE_ATTENDANCE`), rolling quorum shortfall (`ERR_QUORUM_NOT_MET`), rotation tenure (`ERR_ROTATION_LIMIT_EXCEEDED`), sealing an empty package (`ERR_PACKAGE_EMPTY`), and per-corporation email uniqueness (`ERR_DUPLICATE_EMAIL`).
9. **Cross-reference and lifecycle rules** — same-corporation references (`ERR_CROSS_CORPORATION_REFERENCE`), director-active requirements (`ERR_DIRECTOR_NOT_ACTIVE`, `ERR_PROXY_HOLDER_INELIGIBLE`, `ERR_INELIGIBLE_VOTER`), adopted-bylaws presence (`ERR_NO_ADOPTED_BYLAWS`), at least one active director at notice time (`ERR_NO_ACTIVE_DIRECTORS`), in-session requirements for votes (`ERR_MEETING_NOT_IN_SESSION`), no open votes at adjournment (`ERR_UNRESOLVED_VOTES_EXIST`), and adopted clearing resolutions (`ERR_CLEARING_RESOLUTION_NOT_ADOPTED`).

A request failing an earlier tier never reaches a later one: a ballot cast without headers reports `ERR_MISSING_CONTEXT_HEADER` even if the caller also had the wrong role, and a duplicate ballot surfaces only after the context, role, schema, existence, state, temporal, and compliance tiers have all passed.

## 3. Business Logic & Workflows

This section walks the governance lifecycle as the secretary's office lives it: standing up the corporation, seating the board, chartering committees, convening meetings, deciding resolutions, policing conflicts, and closing the minute book. Capabilities are named by their business act; the HTTP contract for each is tabulated in §4.

### 3.1. Standing Up the Corporation and Its Bylaws

A corporate secretary begins by registering the corporation itself, supplying its legal `name` and the two-letter `incorporation_state` code. The new corporation starts with `active_director_count` at zero and `current_bylaws_id` null. Corporations can be listed — optionally filtered by `current_bylaws_id` — and fetched individually by any role.

With a corporation registered, the secretary drafts its bylaws. A bylaws draft captures eleven policy values, each validated at intake with out-of-range or malformed values rejected as `ERR_VALIDATION`: `notice_days_regular` and `notice_days_special`, the days of notice owed before REGULAR or ANNUAL meetings and before SPECIAL meetings respectively, both zero or greater; `package_lead_days`, the minimum lead time between board package distribution and the meeting start, zero or greater; `quorum_percent`, an integer between 1 and 100 inclusive, and `quorum_fixed_count`, zero or greater, which together define quorum; `consent_window_days`, at least one, and `consent_unanimity_required`, the boolean that chooses between unanimous and majority written consent; `minute_retention_years`, at least one; `rotation_max_years`, at least one; and `board_seat_count`, at least one. Each draft is stamped with a `version_no` one greater than the highest existing number for that corporation and begins life in `DRAFT`.

Adoption is the pivotal act of the rulebook lifecycle. The secretary adopts a `DRAFT` bylaws, and the request must carry `expected_corporation_version` per §2.7 — a stale value is refused with `ERR_STALE_VERSION` (HTTP 412). On adoption the bylaws records `adopted_at` from the current clock and moves `DRAFT` → `ADOPTED`; the corporation's previously adopted bylaws, if any, moves `ADOPTED` → `SUPERSEDED` with its `superseded_by_id` pointing at the newcomer; the corporation's `current_bylaws_id` is repointed to the newly adopted set; and the corporation's `version` increments by one. `SUPERSEDED` is terminal — a displaced bylaws is never revived, only preserved as history. Bylaws may be listed with `corporation_id`, `status`, and `superseded_by_id` filters, and fetched individually. Many downstream operations presuppose that an adopted rulebook exists and fail with `ERR_NO_ADOPTED_BYLAWS` (HTTP 422) when none does.

### 3.2. Board Composition: Appointments, Seats, and Independence

Directors join the board by secretary appointment. The appointment payload carries `full_name`, `email`, and the elected term from `term_start` (inclusive) to `term_end` (exclusive); an end that is not strictly after the start is malformed (`ERR_VALIDATION`). Email addresses are unique within a corporation, and a second appointment reusing one is refused with `ERR_DUPLICATE_EMAIL` (HTTP 409). A newly appointed director begins in `ACTIVE` status with `independence_status` preset to `PENDING_REVIEW`, and the corporation's `active_director_count` rises by one.

Seat capacity is enforced instant by instant across the whole term, not just at its edges. At every moment within the half-open span of the proposed term, the platform counts the corporation's `ACTIVE` directors whose own half-open terms cover that moment; if adding the newcomer would push that occupancy above the adopted bylaws' `board_seat_count` at any moment, the appointment is rejected with `ERR_SEAT_CAPACITY_EXCEEDED` (HTTP 422). Reaching exactly the seat ceiling everywhere is permitted — only exceeding it fails. When the corporation has no adopted bylaws, the capacity check is skipped and seats are unbounded.

Independence classification is a standing obligation rather than a creation-time fact. The secretary reviews a director and sets `independence_status` to `INDEPENDENT`, `NON_INDEPENDENT`, or back to `PENDING_REVIEW`; the classification feeds audit-committee eligibility (§3.3) and RESTRICTED document clearance (§3.5). Directors may be listed with `corporation_id`, `status`, and `independence_status` filters.

Departure comes in two forms. A director may resign — recorded either by the secretary or by the director themselves, with a `Director` caller's `X-User-ID` required to equal the departing director's `id` — provided the director is still `ACTIVE`, otherwise `ERR_INVALID_STATE_TRANSITION`. Resignation moves the director `ACTIVE` → `RESIGNED` and cascades: every committee membership of that director still `ACTIVE` ends with `ended_reason` set to `DIRECTOR_RESIGNED`; each affected committee recomputes `chair_vacant` (true when no `ACTIVE` membership with `committee_role` `CHAIR` remains) and, if its `active_member_count` has fallen below its `quorum_fixed_count`, slips from `ACTIVE` to `BELOW_QUORUM`; and the corporation's `active_director_count` drops by one. The second form is term expiry: when the governance checkpoint runs (§3.9) and the current clock has passed a director's `term_end`, the director moves `ACTIVE` → `TERM_EXPIRED` with the identical cascade, except that ended memberships record `ended_reason` `DIRECTOR_TERM_EXPIRED`. Both `RESIGNED` and `TERM_EXPIRED` are terminal.

### 3.3. Committees, Membership, and Rotation Limits

Committees structure the board's working groups. The secretary creates one with a `corporation_id`, a display `name`, a `committee_type` of `AUDIT`, `COMPENSATION`, `NOMINATING`, or `SPECIAL`, the `charter_text`, and a `quorum_fixed_count` of at least one — the minimum `ACTIVE` membership at which the committee may act. A committee is born in `CHARTER_DRAFT`. Activation, a secretary act, requires the charter to be non-empty — activating with blank `charter_text` is `ERR_VALIDATION` — and moves the committee `CHARTER_DRAFT` → `ACTIVE`. Dissolution, also a secretary act, is available from `CHARTER_DRAFT`, `ACTIVE`, or `BELOW_QUORUM` (anything else is `ERR_INVALID_STATE_TRANSITION`); it moves the committee to the terminal `DISSOLVED` state and ends every `ACTIVE` membership with `ended_reason` `COMMITTEE_DISSOLVED`. Committees list with `corporation_id`, `status`, and `committee_type` filters.

Membership is where rotation policy bites. The secretary adds a director to a committee with `committee_id`, `director_id`, a `committee_role` of `CHAIR` or `MEMBER`, and a term from `term_start` (inclusive) to `term_end` (exclusive, strictly after the start). Four guards protect the add, beyond the schema and existence tiers: the director must be `ACTIVE` (`ERR_DIRECTOR_NOT_ACTIVE`, HTTP 422); the director and committee must belong to the same corporation (`ERR_CROSS_CORPORATION_REFERENCE`); an `AUDIT` committee admits only directors whose `independence_status` is `INDEPENDENT` (`ERR_AUDIT_COMMITTEE_INDEPENDENCE`, HTTP 422); and a committee seats at most one `ACTIVE` chair at a time. On a successful add the committee's `active_member_count` rises by one, `chair_vacant` is recomputed, and a committee previously starved below quorum returns `BELOW_QUORUM` → `ACTIVE` once its count again reaches its `quorum_fixed_count`. Memberships list with `committee_id`, `director_id`, and `status` filters.

The rotation guard totals a director's service on that specific committee. Every membership row for the same director-and-committee pair — whether still `ACTIVE` or long since `ENDED` — contributes its length in days divided by 365, and the proposed membership contributes its own length computed the same way. The running total is rounded half up to two decimal places, and if that figure strictly exceeds the adopted bylaws' `rotation_max_years` the add is refused with `ERR_ROTATION_LIMIT_EXCEEDED` (HTTP 422); a total landing exactly on the limit passes. When the corporation has no adopted bylaws, the rotation check is skipped.

Ending a membership is normally a manual secretary act: the membership moves `ACTIVE` → `ENDED` with `ended_reason` `MANUAL`, the committee's `active_member_count` falls by one, `chair_vacant` is recomputed, and a committee whose count drops below its `quorum_fixed_count` moves `ACTIVE` → `BELOW_QUORUM`. The same committee re-evaluation accompanies the `DIRECTOR_RESIGNED`, `DIRECTOR_TERM_EXPIRED`, and `COMMITTEE_DISSOLVED` endings described elsewhere.

### 3.4. The Meeting Lifecycle: Scheduling, Notice, Attendance, and Adjournment

Scheduling a meeting is a secretary act carrying `corporation_id`, a `meeting_type` of `REGULAR`, `SPECIAL`, or `ANNUAL`, the `scheduled_start`, the planned `duration_minutes`, the `location_or_medium`, and the presiding `chair_director_id`. The start must lie strictly after the current clock — a past or exactly-current start is `ERR_SCHEDULED_START_IN_PAST` (HTTP 422) — and the designated chair must be an `ACTIVE` director of the same corporation (`ERR_DIRECTOR_NOT_ACTIVE`, or `ERR_CROSS_CORPORATION_REFERENCE` when the chair belongs elsewhere). The meeting occupies a half-open calendar window from `scheduled_start` up to but not including `scheduled_start` plus `duration_minutes`. If any other meeting of the same corporation that is not `CANCELLED` holds a window starting strictly before the new window's end and ending strictly after the new window's start, the schedule is refused with `ERR_MEETING_TIME_CONFLICT` (HTTP 409); back-to-back meetings whose windows merely touch are permitted. A successfully scheduled meeting begins in `SCHEDULED`. Meetings list with `corporation_id`, `status`, `chair_director_id`, and `bylaws_id_at_notice` filters.

Notice converts a calendar entry into a governed obligation. Sending notices — a secretary act on a `SCHEDULED` meeting — requires an adopted bylaws (`ERR_NO_ADOPTED_BYLAWS`) and at least one `ACTIVE` director (`ERR_NO_ACTIVE_DIRECTORS`, HTTP 422). The server then creates one MeetingNotice per `ACTIVE` director: `sent_at` takes the current clock; `required_notice_days` is snapshotted from the adopted bylaws as `notice_days_special` for a `SPECIAL` meeting and `notice_days_regular` for `REGULAR` or `ANNUAL`; `deadline_at` is the scheduled start moved back by that many full days, each day counted as 86,400 seconds; and `is_timely` records whether the notice went out on or before its deadline — dispatch exactly at the deadline counts as timely, and the flag is also re-derived whenever a notice is read. The meeting pins `bylaws_id_at_notice` to the adopted bylaws' `id` and moves `SCHEDULED` → `NOTICED`. A director may waive only their own notice, moving it `SENT` → `WAIVED` with `waived_at` stamped from the clock; a `Director` caller whose `X-User-ID` names any other director's notice is refused with `ERR_FORBIDDEN_ROLE`. A waived notice is treated as satisfied regardless of the deadline arithmetic. Notices list with `meeting_id`, `director_id`, and `status` filters.

Plans change, and rescheduling is the governed way to move a `SCHEDULED` or `NOTICED` meeting. The secretary supplies the new `scheduled_start`, the new `duration_minutes`, and — non-optionally — `expected_meeting_version` per §2.7; a version that trails the meeting's current `version` is refused with `ERR_STALE_MEETING_VERSION` (HTTP 412). The new start is held to the same future-dating rule (`ERR_SCHEDULED_START_IN_PAST`) and the same half-open overlap rule (`ERR_MEETING_TIME_CONFLICT`), with the meeting being moved excluded from the comparison set. A successful reschedule replaces the window, deletes every MeetingNotice already issued for the meeting — notice must be sent afresh against the new date — returns the meeting to `SCHEDULED`, and increments the meeting's `version`.

Cancellation, available to the secretary or the chair from `SCHEDULED`, `NOTICED`, or `IN_SESSION`, is the widest cascade in the API. Every agenda item of the meeting in `PROPOSED` or `INCLUDED` drops to `DROPPED`; each dropped item that names a `resolution_id` whose resolution stands `TABLED` or `VOTE_OPEN` sends that resolution back to `DRAFT`, and every `ACTIVE` vote record on such a resolution is `VOIDED`; and the meeting's board package, if still `ASSEMBLING` or `SEALED`, is `WITHDRAWN` — an already `DISTRIBUTED` package remains distributed. `CANCELLED` meetings are exempt from future calendar overlap checks.

Convening belongs to the chair alone: the caller's `X-User-ID` must equal the meeting's `chair_director_id` (`ERR_FORBIDDEN_ROLE`), the meeting must be `NOTICED`, and the current clock must have reached `scheduled_start` — convening early is `ERR_MEETING_NOT_YET` (HTTP 422). At the call to order the server stamps `convened_at` and freezes a quorum snapshot onto the meeting: `quorum_required_count` is the greater of the pinned bylaws' `quorum_fixed_count` and the ceiling of `quorum_percent` multiplied by the corporation's current `ACTIVE` director count and divided by one hundred — the ceiling is applied to the percentage product first, and only then is the maximum taken; `quorum_present_snapshot` counts the meeting's attendance records whose `attendance_mode` is `IN_PERSON`, `REMOTE`, or `PROXY`, excluding `ABSENT`; and `quorum_met` records whether presence reached the requirement, with an exact head-count tie counting as quorum present. The meeting is then `IN_SESSION`.

Attendance is the evidentiary feed for quorum. The secretary records each director's presence — for a `NOTICED` or `IN_SESSION` meeting — with `meeting_id`, `director_id`, an `attendance_mode` of `IN_PERSON`, `REMOTE`, `PROXY`, or `ABSENT`, and, for proxies, a `proxy_holder_director_id`. Only one record may exist per meeting-and-director pair; a second is `ERR_DUPLICATE_ATTENDANCE` (HTTP 409). A `PROXY` record is valid only when `proxy_holder_director_id` is present, names someone other than the attendee, and names an `ACTIVE` director of the same corporation — otherwise `ERR_PROXY_HOLDER_INELIGIBLE` (HTTP 422). Each record's `recorded_at` takes the logical clock. Attendance lists with `meeting_id`, `director_id`, and `proxy_holder_director_id` filters.

Adjournment, again a chair-only act requiring the caller to be the meeting's `chair_director_id`, closes an `IN_SESSION` meeting — but only when no resolution of the meeting still stands `VOTE_OPEN`; adjourning over an open vote is `ERR_UNRESOLVED_VOTES_EXIST` (HTTP 409). The moment a meeting moves `IN_SESSION` → `ADJOURNED`, the server auto-creates its Minutes record in `DRAFT` with empty `content`; exactly one minutes record ever exists per meeting.

### 3.5. Agendas, Board Packages, and Document Access Tiers

An agenda takes shape while its meeting is still `SCHEDULED` or `NOTICED`. The secretary or a director proposes an item with `meeting_id`, a `title`, an `order_index` of at least 1 fixing display order, the `proposed_by_director_id`, and optionally a `resolution_id` linking the item to the resolution to be voted under it; the item begins `PROPOSED`. The secretary then includes proposed items into the working agenda — `PROPOSED` → `INCLUDED` — but only while the meeting remains `SCHEDULED` or `NOTICED`; once the meeting has advanced past notice, the agenda is locked and inclusion fails with `ERR_AGENDA_LOCKED` (HTTP 422). Dropping, from `PROPOSED` or `INCLUDED`, moves an item to the terminal `DROPPED` state, and when the dropped item names a `resolution_id` whose resolution is `TABLED` or `VOTE_OPEN`, that resolution reverts to `DRAFT` and its `ACTIVE` ballots are `VOIDED` — the same cascade the meeting cancellation applies. Agenda items list with `meeting_id`, `resolution_id`, `proposed_by_director_id`, and `status` filters.

The board package is the meeting's reading matter. The secretary creates one for a `SCHEDULED` or `NOTICED` meeting; it begins `ASSEMBLING` with `seal_count` and `document_count` at zero. Documents are added to an `ASSEMBLING` package with `package_id`, a `title`, an opaque `content_ref` pointing at the stored content, and a `confidentiality_tier`; each addition raises the package's `document_count`. Sealing freezes the assembly: it requires the package to be `ASSEMBLING`, to hold at least one document (`ERR_PACKAGE_EMPTY`, HTTP 422), and to belong to a meeting still `SCHEDULED` or `NOTICED`; a seal stamps `sealed_at` from the clock and increments `seal_count`. A sealed package can be reopened for corrections — `SEALED` → `ASSEMBLING` — and sealed again later. Distribution releases a `SEALED` package, but only within the bylaws lead window: the current clock must be no later than the meeting's `scheduled_start` minus the `package_lead_days` of the governing bylaws — the set pinned at notice when `bylaws_id_at_notice` is set, otherwise the corporation's currently adopted set — and a distribution attempted past that boundary is `ERR_PACKAGE_DISTRIBUTION_LATE` (HTTP 422). Distribution stamps `distributed_at` and moves the package to the terminal `DISTRIBUTED` state; a package caught `ASSEMBLING` or `SEALED` when its meeting is cancelled is `WITHDRAWN` instead. Packages list with `meeting_id` and `status` filters; documents list with `package_id` and `confidentiality_tier` filters.

Access to package documents follows the tier. A `GENERAL` document is visible to every director; a `CONFIDENTIAL` document is visible to `ACTIVE` directors only; a `RESTRICTED` document is visible solely to `ACTIVE` directors whose `independence_status` is `INDEPENDENT`. When a `Director` or `BoardChair` caller lists documents, the result is silently filtered to the tiers that caller may read; when such a caller fetches a single document above their clearance, the read is refused outright with `ERR_PACKAGE_ACCESS_DENIED` (HTTP 403). `CorporateSecretary` and `ExternalAuditor` readers see everything unfiltered.

### 3.6. Resolutions in Session: Tabling, Ballots, and Outcomes

A resolution is the board's unit of decision. Drafting one — open to the secretary and to directors — takes `corporation_id`, an `origin` of `MEETING` or `WRITTEN_CONSENT`, a `resolution_type` of `ORDINARY` or `SPECIAL`, a `title`, the body `text`, an optional `related_party` naming a counterparty that triggers recusal duties, and a `meeting_id` that is required when the origin is `MEETING` and must be null when the origin is `WRITTEN_CONSENT`. Every resolution begins in `DRAFT`. Resolutions list with `corporation_id`, `meeting_id`, `status`, and `consent_bylaws_id` filters.

The floor path starts with tabling: the secretary or the chair tables a `DRAFT` resolution of `MEETING` origin whose linked meeting is `NOTICED` or `IN_SESSION`, moving it to `TABLED`; tabling is undefined for consent-origin drafts and for meetings outside those states (`ERR_INVALID_STATE_TRANSITION`). When the board is ready to decide, the chair opens the vote. Opening requires the resolution to be `TABLED`, the linked meeting to be `IN_SESSION` (`ERR_MEETING_NOT_IN_SESSION`, HTTP 422), and rolling quorum: a fresh count of the meeting's attendance records with `attendance_mode` in `IN_PERSON`, `REMOTE`, or `PROXY` must reach the stored `quorum_required_count`, else `ERR_QUORUM_NOT_MET` (HTTP 422). Because this rolling presence is re-evaluated at every vote opening from all current attendance records, directors who arrive after a failed convene snapshot can still lift the meeting over quorum. The resolution is then `VOTE_OPEN`. The chair may also withdraw an open question from the floor — `VOTE_OPEN` → `TABLED` — which voids every `ACTIVE` ballot already cast on it.

While a resolution stands `VOTE_OPEN`, directors cast ballots carrying `resolution_id`, a `channel` of `MEETING_BALLOT`, and a `vote` of `FOR`, `AGAINST`, `ABSTAIN`, or `RECUSED`; each cast creates an `ACTIVE` vote record whose `director_id` is taken from the caller's `X-User-ID`, whose `cast_at` takes the logical clock, and whose `recast_count` starts at zero. Casting is a director-only, self-scoped act guarded by a chain of rules: the resolution must be `VOTE_OPEN` (otherwise `ERR_INVALID_STATE_TRANSITION`) and its meeting must be `IN_SESSION` (`ERR_MEETING_NOT_IN_SESSION`); the caster must be an `ACTIVE` director who is present at the meeting — an attendance record in any mode other than `ABSENT` — else `ERR_INELIGIBLE_VOTER` (HTTP 422); a director holding an `OPEN` conflict disclosure whose `related_party` matches the resolution's must vote `RECUSED`, and any other value from them is `ERR_CONFLICT_RECUSAL_REQUIRED` (HTTP 422); and at most one `ACTIVE` record may exist per resolution, director, and channel — a second is `ERR_DUPLICATE_VOTE` (HTTP 409). A caster may change their mind while the vote remains open: recasting replaces the `vote` on their own `ACTIVE` ballot, increments `recast_count`, recomputes the resolution's tallies, and leaves the count of `ACTIVE` ballots unchanged. Recasting is self-scoped — only the original caster's `X-User-ID` is honored — and closes the moment the resolution leaves `VOTE_OPEN`.

Four tallies live on the resolution — `for_count`, `against_count`, `abstain_count`, and `recused_count` — all zero while the resolution is a draft, thereafter counting its `ACTIVE` vote records of each value and recomputed on every cast, recast, and voiding. When the chair closes the vote on a `VOTE_OPEN` resolution, the outcome is decided against the eligible pool: the directors `ACTIVE` at close time, minus those holding an `OPEN` disclosure whose `related_party` matches the resolution's at that moment. An `ORDINARY` resolution follows the present-and-voting variant and is adopted if and only if twice its `for_count` strictly exceeds the sum of `for_count` and `against_count` — abstentions, recusals, and absent directors enter no denominator. A `SPECIAL` resolution follows the full-board-majority variant and is adopted if and only if its `for_count` reaches at least the integer floor of half the eligible pool plus one — here abstentions and absentees weigh against adoption. Closing stamps `closed_at` from the clock, recomputes the tallies, and moves the resolution to `ADOPTED` or `REJECTED` accordingly. A `REJECTED` resolution is not necessarily dead: the secretary may redraft it back to `DRAFT`, voiding any remaining `ACTIVE` ballots, resetting all four tallies to zero, and clearing its consent fields.

### 3.7. Action by Written Consent

Written consent lets the board act between meetings. The secretary circulates a `DRAFT` resolution of `WRITTEN_CONSENT` origin — attempting the transition on any other state or origin is `ERR_INVALID_STATE_TRANSITION` — and circulation requires an adopted bylaws (`ERR_NO_ADOPTED_BYLAWS`). Circulation pins three things onto the resolution: `consent_bylaws_id`, the currently adopted bylaws whose rules will govern this consent no matter what is adopted later; `consent_deadline_at`, the current clock advanced by that bylaws' `consent_window_days`; and `consent_required_count`, computed in a pinned evaluation order so the number can never be gamed retroactively.

That pinned order matters and runs as follows. First, take the set of directors who are `ACTIVE` at the circulation instant. Second, remove from that set every director holding an `OPEN` conflict disclosure whose `related_party` matches the resolution's. Third, if the pinned bylaws' `consent_unanimity_required` is true, the required count is the size of the remaining set — every non-recused active director must sign; if it is false, the required count is the integer floor of half the remaining set plus one. Fourth, the count is stored on the resolution and never changes afterward: disclosures filed later, clearances, and resignations leave the stored requirement untouched. The resolution is then `CIRCULATING`.

Signing is a director's self-scoped act through a vote record whose `channel` is `WRITTEN_CONSENT`. The consent channel is narrower than the ballot box: it admits only `FOR` and `AGAINST`, and a payload offering `ABSTAIN` or `RECUSED` on it is malformed (`ERR_VALIDATION`). Signing after `consent_deadline_at` is refused with `ERR_CONSENT_DEADLINE_PASSED` (HTTP 422). A signature counts only from a signer who belonged to the non-recused active set frozen at circulation and is still `ACTIVE` at signing time — anyone else is `ERR_INELIGIBLE_VOTER` — and a signer holding an `OPEN` disclosure matching the resolution's `related_party` is refused with `ERR_CONFLICT_RECUSAL_REQUIRED`, a compliance check that fires before the eligibility tier per §2.11. The one-record-per-resolution-director-channel rule applies here too (`ERR_DUPLICATE_VOTE`), and consents are never recast.

Finalization settles a circulation, whether the secretary runs it directly or the governance checkpoint evaluates it. When the count of `ACTIVE` consent records voting `FOR` has reached the stored `consent_required_count`, the resolution moves `CIRCULATING` → `CONSENT_ADOPTED` with `closed_at` stamped. When the current clock has passed `consent_deadline_at` and the `FOR` tally still falls short, the resolution moves `CIRCULATING` → `CONSENT_LAPSED`, again stamping `closed_at`. A lapsed consent may be redrafted to `DRAFT` exactly like a rejected floor resolution — outstanding consent records are `VOIDED`, tallies reset to zero, and the consent fields cleared for another attempt.

### 3.8. Conflict Disclosure and Recusal

Disclosure is how the board keeps interested directors out of interested decisions. A filing — by the secretary, or by a director for themselves with `X-User-ID` equal to the disclosed `director_id` — carries `director_id`, `corporation_id`, the `related_party` the director is conflicted with, and a window from `effective_from` through `effective_to`; the window is a closed interval, so its end may equal but not precede its start (`ERR_VALIDATION`). An optional `description` narrates the conflict, and an optional `clearing_resolution_id` names the resolution whose adoption will discharge it. A new disclosure begins `OPEN`. Two disclosures of the same director for the same `related_party` may not overlap while both are `OPEN`: because the windows are closed intervals, a filing whose start falls on the exact day an existing window ends is already a conflict, rejected with `ERR_DISCLOSURE_WINDOW_CONFLICT` (HTTP 409). Disclosures list with `director_id`, `corporation_id`, `status`, `related_party`, and `clearing_resolution_id` filters.

Clearance is a secretary act moving a disclosure `OPEN` → `CLEARED` and stamping `cleared_at`. When the filing recorded a `clearing_resolution_id`, clearance is blocked until that resolution stands `ADOPTED` or `CONSENT_ADOPTED`; clearing early is `ERR_CLEARING_RESOLUTION_NOT_ADOPTED` (HTTP 422).

Recusal is where disclosure bites into voting. At ballot time (§3.6) a director with an `OPEN` disclosure matching the resolution's `related_party` may cast only `RECUSED`; at consent time (§3.7) such a director may not sign at all. Recused directors are excluded from every denominator that matters: the eligible pool at vote close, and the circulation-time snapshot behind `consent_required_count`.

### 3.9. Minutes, the Minute Book, Retention, and Audit Reconstruction

Minutes are born at adjournment: one Minutes record per meeting, keyed by `meeting_id`, with `corporation_id` denormalized from the meeting so the book can be queried directly. A fresh minutes record stands `DRAFT` with empty `content` and `review_round` at zero.

The approval cycle is a dialogue between secretary and chair. The secretary circulates a `DRAFT` minutes with a `content` payload, moving it `DRAFT` → `CIRCULATED_FOR_REVIEW`; each circulation stores the supplied `content` and increments `review_round`. The chair of the linked meeting — and only that chair, with `X-User-ID` matched against the meeting's `chair_director_id` (`ERR_FORBIDDEN_ROLE`) — then decides. Approval requires the minutes to be `CIRCULATED_FOR_REVIEW` and the linked meeting `ADJOURNED`; it stamps `approved_at` from the clock and computes `retention_until` as `approved_at` advanced by the `minute_retention_years` of the corporation's currently adopted bylaws, moving the minutes to `APPROVED`. Rejection of a `CIRCULATED_FOR_REVIEW` minutes, with a `reason` payload, moves the minutes to `REJECTED` and records the reason in `rejection_reason`. The secretary may then redraft — a fresh `content` payload returns the minutes `REJECTED` → `DRAFT` and clears `rejection_reason` — and the circulate-review loop may run as many rounds as needed, `review_round` climbing each time.

Entry into the minute book is the point of permanence. The secretary enters an `APPROVED` minutes, which moves it to `ENTERED_IN_BOOK` and stamps two evidentiary fields: `book_seq_no`, one greater than the highest `book_seq_no` already entered for that corporation — zero when the book is empty — so the sequence is gap-free, and `content_hash`, the lowercase SHA-256 hexadecimal of the `content`. The minute book itself is simply the minutes listing filtered to `status` `ENTERED_IN_BOOK` for a `corporation_id`, ordered by `book_seq_no` rather than the default creation order; minutes otherwise list with `meeting_id`, `corporation_id`, and `status` filters.

Retention has a horizon and a puritanical edge. When the governance checkpoint runs, every minutes record `ENTERED_IN_BOOK` whose `retention_until` lies strictly before the current clock moves to the terminal `PURGED` state — a clock exactly equal to the retention instant retains the record. Purging clears `content` to the empty string but keeps `content_hash`, so the book remains tamper-evident even after its pages are gone.

Audit reconstruction is the external check on all of this. An `ExternalAuditor` or the secretary opens an AuditRequest with `corporation_id`, a free-text `requested_by_label`, and an inclusive reconstruction window from `scope_start` through `scope_end` — an end earlier than the start is `ERR_VALIDATION` — and the request begins `OPEN`. Running reconstruction (either role, from `OPEN` or from `FAILED`, so a failed attempt may be retried) moves the request to `RECONSTRUCTING` and evaluates synchronously. The gap check runs first: if any meeting inside the window has its minutes in `PURGED` status, the request collapses to `FAILED`, setting `failure_reason` and leaving `reconstruction_log` null. Otherwise the request settles into the terminal `COMPLETED` state, projecting the corporation's history into an ordered `reconstruction_log`. The sources are the corporation's meetings by their `created_at`, its resolutions in `ADOPTED` or `REJECTED` by their `closed_at`, and its approved minutes by their `approved_at` — each admitted when its relevant timestamp falls inside the inclusive scope window. Entries order by that timestamp ascending, then by source-type rank — meetings first, then resolutions, then minutes — and any remaining ties by the source row's `created_at` ascending; record ids are never used for ordering. Each entry carries a one-based `seq`, its `source_type`, its `source_id`, and its `occurred_at`. The completion stamps `entry_count` with the number of entries, and `reconstruction_digest` with the lowercase SHA-256 hexadecimal over the concatenated lines, each line of the form `seq|source_type|source_id|occurred_at`.

Alongside the digest, completion computes `governance_approval_rate_pct`. For every resolution of the corporation that closed — `ADOPTED` or `REJECTED` — with `closed_at` inside the scope window, the eligible pool is the directors `ACTIVE` at that resolution's `closed_at` minus those recused at that moment; a resolution whose pool is zero is skipped entirely. Each remaining resolution contributes the percentage of its `for_count` over its pool, rounded half up to one decimal place — the rounding happens per resolution, before any averaging. The reported rate is the arithmetic mean of those per-resolution percentages, itself rounded half up to one decimal place. A pooled alternative — summing all FOR tallies over the summed eligible pools — is deliberately not used. Audit requests list with `corporation_id` and `status` filters.

The governance checkpoint itself is the secretary's ops-run over a single corporation, and it bundles three sweeps into one call. It expires every `ACTIVE` director whose `term_end` has passed, with the full resignation-style cascade of §3.2 recorded as `DIRECTOR_TERM_EXPIRED`. It evaluates every `CIRCULATING` written consent: any whose `FOR` signatures have reached the stored requirement is adopted, and any whose deadline has passed while still short of the requirement is lapsed. And it purges entered minutes past their retention instant as described above. The run reports back four rosters: `expired_director_ids`, `lapsed_resolution_ids`, `adopted_resolution_ids`, and `purged_minutes_ids`.

## 4. Endpoint Definitions

Operations that create a new resource in a collection return `201 Created`; operations that modify an existing resource or drive a lifecycle action return `200 OK`. All collections are flat, root-level paths — corporation scoping is expressed through `corporation_id` fields and filters, never through nested URLs. Request payloads, response contents, and side effects for each operation are governed by the narratives of §2 and §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical governance clock | CorporateSecretary |
| POST | `/corporations` | Create a corporation | CorporateSecretary |
| GET | `/corporations` | List corporations | All roles |
| GET | `/corporations/{id}` | Get one corporation | All roles |
| POST | `/corporations/{id}/run_checkpoint` | Run the governance checkpoint: term expiry, consent lapse/adoption, retention purge | CorporateSecretary |
| POST | `/bylaws` | Create a DRAFT bylaws version | CorporateSecretary |
| GET | `/bylaws` | List bylaws | All roles |
| GET | `/bylaws/{id}` | Get one bylaws | All roles |
| POST | `/bylaws/{id}/adopt` | Adopt a DRAFT bylaws, superseding the currently ADOPTED one | CorporateSecretary |
| POST | `/directors` | Appoint a director; enforces seat capacity and email uniqueness | CorporateSecretary |
| GET | `/directors` | List directors | All roles |
| GET | `/directors/{id}` | Get one director | All roles |
| POST | `/directors/{id}/resign` | Resign a director; cascades to memberships and committees | CorporateSecretary, Director |
| POST | `/directors/{id}/review_independence` | Set a director's independence classification | CorporateSecretary |
| POST | `/committees` | Create a committee in CHARTER_DRAFT | CorporateSecretary |
| GET | `/committees` | List committees | All roles |
| GET | `/committees/{id}` | Get one committee | All roles |
| POST | `/committees/{id}/activate` | Activate a committee charter | CorporateSecretary |
| POST | `/committees/{id}/dissolve` | Dissolve a committee, ending all ACTIVE memberships | CorporateSecretary |
| POST | `/committee_memberships` | Add a director to a committee | CorporateSecretary |
| GET | `/committee_memberships` | List memberships | All roles |
| GET | `/committee_memberships/{id}` | Get one membership | All roles |
| POST | `/committee_memberships/{id}/end` | End a membership | CorporateSecretary |
| POST | `/meetings` | Schedule a meeting; enforces future start and half-open calendar overlap | CorporateSecretary |
| GET | `/meetings` | List meetings | All roles |
| GET | `/meetings/{id}` | Get one meeting, including quorum fields | All roles |
| POST | `/meetings/{id}/send_notices` | Send one notice per ACTIVE director and pin the bylaws | CorporateSecretary |
| POST | `/meetings/{id}/reschedule` | Move a SCHEDULED/NOTICED meeting; OCC-guarded; deletes issued notices | CorporateSecretary |
| POST | `/meetings/{id}/cancel` | Cancel a meeting; cascades agenda, resolutions, ballots, and packages | CorporateSecretary, BoardChair |
| POST | `/meetings/{id}/convene` | Call the meeting to order; computes the quorum snapshot | BoardChair |
| POST | `/meetings/{id}/adjourn` | Adjourn the meeting; auto-creates its Minutes in DRAFT | BoardChair |
| GET | `/meeting_notices` | List notices | All roles |
| GET | `/meeting_notices/{id}` | Get one notice | All roles |
| POST | `/meeting_notices/{id}/waive` | Director waives their own notice | Director |
| POST | `/attendance_records` | Record attendance for a NOTICED or IN_SESSION meeting | CorporateSecretary |
| GET | `/attendance_records` | List attendance records | All roles |
| GET | `/attendance_records/{id}` | Get one attendance record | All roles |
| POST | `/agenda_items` | Propose an agenda item for a SCHEDULED or NOTICED meeting | CorporateSecretary, Director |
| GET | `/agenda_items` | List agenda items | All roles |
| GET | `/agenda_items/{id}` | Get one agenda item | All roles |
| POST | `/agenda_items/{id}/include` | Include a proposed item into the agenda | CorporateSecretary |
| POST | `/agenda_items/{id}/drop` | Drop an agenda item | CorporateSecretary |
| POST | `/board_packages` | Create a board package for a SCHEDULED or NOTICED meeting | CorporateSecretary |
| GET | `/board_packages` | List packages | All roles |
| GET | `/board_packages/{id}` | Get one package | All roles |
| POST | `/board_packages/{id}/seal` | Seal a non-empty package | CorporateSecretary |
| POST | `/board_packages/{id}/unseal` | Reopen a sealed package for corrections | CorporateSecretary |
| POST | `/board_packages/{id}/distribute` | Distribute a sealed package within the bylaws lead window | CorporateSecretary |
| POST | `/package_documents` | Add a document to an ASSEMBLING package | CorporateSecretary |
| GET | `/package_documents` | List documents; filtered to caller-visible tiers for Director/BoardChair | All roles |
| GET | `/package_documents/{id}` | Get one document; tier clearance enforced | All roles |
| POST | `/resolutions` | Draft a resolution; MEETING origin requires a meeting, WRITTEN_CONSENT forbids one | CorporateSecretary, Director |
| GET | `/resolutions` | List resolutions | All roles |
| GET | `/resolutions/{id}` | Get one resolution | All roles |
| POST | `/resolutions/{id}/table` | Table a draft onto the floor, or withdraw an open vote back to TABLED | CorporateSecretary, BoardChair |
| POST | `/resolutions/{id}/open_vote` | Open the floor vote; requires IN_SESSION meeting and rolling quorum | BoardChair |
| POST | `/resolutions/{id}/close_vote` | Close voting and compute ADOPTED or REJECTED | BoardChair |
| POST | `/resolutions/{id}/redraft` | Return a REJECTED or CONSENT_LAPSED resolution to DRAFT | CorporateSecretary |
| POST | `/resolutions/{id}/circulate_consent` | Start written-consent circulation; pins bylaws, required count, deadline | CorporateSecretary |
| POST | `/resolutions/{id}/finalize_consent` | Finalize a circulation: adopt on sufficient signatures, lapse past deadline | CorporateSecretary |
| POST | `/vote_records` | Cast a ballot or sign a consent; caster identity from X-User-ID | Director |
| GET | `/vote_records` | List vote records | All roles |
| GET | `/vote_records/{id}` | Get one vote record | All roles |
| POST | `/vote_records/{id}/recast` | Change the caster's own ACTIVE ballot while the vote is open | Director |
| POST | `/conflict_disclosures` | File a conflict disclosure | CorporateSecretary, Director |
| GET | `/conflict_disclosures` | List disclosures | All roles |
| GET | `/conflict_disclosures/{id}` | Get one disclosure | All roles |
| POST | `/conflict_disclosures/{id}/clear` | Clear an OPEN disclosure | CorporateSecretary |
| GET | `/minutes` | List minutes; the ENTERED_IN_BOOK view per corporation is the minute book | All roles |
| GET | `/minutes/{id}` | Get one minutes record | All roles |
| POST | `/minutes/{id}/circulate` | Circulate draft minutes for review with content | CorporateSecretary |
| POST | `/minutes/{id}/approve` | Chair approves circulated minutes; sets the retention window | BoardChair |
| POST | `/minutes/{id}/reject` | Chair rejects circulated minutes with a reason | BoardChair |
| POST | `/minutes/{id}/redraft` | Return rejected minutes to DRAFT with new content | CorporateSecretary |
| POST | `/minutes/{id}/enter_book` | Enter approved minutes into the minute book | CorporateSecretary |
| POST | `/audit_requests` | Open an audit request over an inclusive scope window | ExternalAuditor, CorporateSecretary |
| GET | `/audit_requests` | List audit requests | All roles |
| GET | `/audit_requests/{id}` | Get one audit request with reconstruction results | All roles |
| POST | `/audit_requests/{id}/reconstruct` | Run minute-book reconstruction synchronously | ExternalAuditor, CorporateSecretary |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_MEETING_TIME_CONFLICT` | 409 Conflict |
| `ERR_DISCLOSURE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_VOTE` | 409 Conflict |
| `ERR_DUPLICATE_ATTENDANCE` | 409 Conflict |
| `ERR_UNRESOLVED_VOTES_EXIST` | 409 Conflict |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_MEETING_VERSION` | 412 Precondition Failed |
| `ERR_SCHEDULED_START_IN_PAST` | 422 Unprocessable Entity |
| `ERR_MEETING_NOT_YET` | 422 Unprocessable Entity |
| `ERR_PACKAGE_DISTRIBUTION_LATE` | 422 Unprocessable Entity |
| `ERR_CONSENT_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_SEAT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_QUORUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_CONFLICT_RECUSAL_REQUIRED` | 422 Unprocessable Entity |
| `ERR_AUDIT_COMMITTEE_INDEPENDENCE` | 422 Unprocessable Entity |
| `ERR_PACKAGE_ACCESS_DENIED` | 403 Forbidden |
| `ERR_INELIGIBLE_VOTER` | 422 Unprocessable Entity |
| `ERR_ROTATION_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CROSS_CORPORATION_REFERENCE` | 422 Unprocessable Entity |
| `ERR_NO_ADOPTED_BYLAWS` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_DIRECTORS` | 422 Unprocessable Entity |
| `ERR_DIRECTOR_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_PROXY_HOLDER_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_MEETING_NOT_IN_SESSION` | 422 Unprocessable Entity |
| `ERR_PACKAGE_EMPTY` | 422 Unprocessable Entity |
| `ERR_AGENDA_LOCKED` | 422 Unprocessable Entity |
| `ERR_CLEARING_RESOLUTION_NOT_ADOPTED` | 422 Unprocessable Entity |
