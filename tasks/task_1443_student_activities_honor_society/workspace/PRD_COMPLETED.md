# NHS Chapter Management API — Product Requirements Document

## 1. Introduction

A National Honor Society chapter runs a full academic-year program that is deceptively hard to administer: the chapter must be chartered and assigned a faculty advisor, candidates must be screened against weighted and unweighted GPA thresholds, service hours must be logged and verified, officers must be elected and their meetings minuted, the activity fund must survive an audit, national dues must be collected and remitted, standards violations must be adjudicated through probation and appeal, and every event must be reconciled against student athletes' game and tournament schedules. Today most chapters track all of this in spreadsheets and email threads, and the invariants that the national organization cares about — a chapter never fronts money it does not have, no student is inducted with an unresolved standards case, no fundraiser is approved twice by the same person — are exactly the invariants that informal tooling lets slip.

This document specifies a REST API that operationalizes the entire chapter lifecycle as a single, consistent system. The API is organized around a **Chapter** aggregate with nested resources for members, membership cycles and their applications, service hour entries, officer elections and votes, officer roles, meeting minutes, fundraiser requests, the fund ledger, dues payments, probation cases, and athletics calendar blocks. A four-tier approval chain — `Member`, `Officer`, `Advisor`, and `ActivitiesDirector` — governs every mutation, with segregation of duties enforced on money movement and optimistic concurrency control on the writes most exposed to stale reads. Temporal rules (nomination windows, induction dates, appeal deadlines) are all evaluated against a server-maintained logical clock so that behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly four roles, spelled precisely as follows: `ActivitiesDirector`, `Advisor`, `Officer`, and `Member`. A request whose `X-User-Role` header is missing or does not carry one of these four values, or whose `X-User-ID` header is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, access to each operation is restricted by role per the endpoint catalogue in §4; an authenticated caller attempting an operation outside their role is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `ActivitiesDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `director_approved_by_user_id` on a fundraiser request) but never compares it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `Advisor`: the identifier is recorded where the workflow calls for it (for example, as `advisor_user_id` on a chapter, `advisor_approved_by_user_id` on a fundraiser, `verified_by_user_id` on a service hour entry, `opened_by_user_id` or `resolved_by_user_id` on a probation case, or `approved_by_user_id` on meeting minutes) but is not the `id` of any stored resource. By contrast, when `X-User-Role` is `Officer`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's foreign-key field to `X-User-ID` — an officer resigning a role, for instance, must present the `id` of the member recorded as that role's office holder. Likewise, when `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`, and member-self operations (withdrawing an application, appealing a probation case, casting a vote) compare the target resource's member reference against it.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; like every server-stamped timestamp in the system (including `created_at` and `updated_at` on resources), it is read from the logical clock of §2.4.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. A `limit` or `offset` that is not an integer or falls outside its bounds is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties — common under the logical clock — broken by creation (insertion) order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Most list endpoints additionally accept optional filter query parameters drawn from the resource's own fields. Depending on the collection these include `status`, `grade_level`, `office`, `entry_type`, `academic_year`, `reason_code`, and `priority`, and the flat list forms accept foreign-key filters such as `chapter_id`, `member_id`, `cycle_id`, `election_id`, `inducted_cycle_id`, `fundraiser_id`, `voter_member_id`, `candidate_member_id`, `called_by_officer_id`, `submitted_by_officer_id`, and `requested_by_officer_id`. A filter parameter restricts the result set to resources whose corresponding field equals the supplied value.

### 2.4. The Logical Clock

Every temporal decision the platform makes — whether nominations are open, whether the induction date has arrived, whether a service date lies in the future, whether a probation appeal window is still open — is evaluated against a **logical clock** maintained by the server, never against real wall-clock time. Before any explicit adjustment, the logical clock reads `2026-08-01T00:00:00Z`. An `ActivitiesDirector` may set the logical clock to a supplied instant through a test-driving capability that accepts a `to_iso8601` timestamp in its payload and echoes the resulting `current_utc` in its response. The server must not fall back to real wall-clock time under any circumstances. Client-supplied timestamps anywhere in the API are parsed as ISO 8601 — a value without an offset is read as UTC — and stored normalized to UTC with three fractional digits. The "current academic year" and "current semester" referenced elsewhere in this document derive from the logical clock: months July through December map to academic year `Y-(Y+1)` and semester `FALL`, and months January through June map to academic year `(Y-1)-Y` and semester `SPRING`.

### 2.5. Common Resource Properties

Every resource in the system — chapters, members, membership cycles, applications, service hour entries, elections, votes, officer roles, meeting minutes, fundraiser requests, ledger entries, dues payments, probation cases, and athletics blocks — carries a standard set of system-managed properties:

- **`id`** (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it is refreshed on every change to the resource.
- **`version`** (integer): an optimistic-concurrency token that starts at 1 on creation and increments by one on every mutation of the resource.

A mutation is not limited to direct client writes. System cascades (for example, applications swept into review when nominations close) and recomputation of derived fields (such as a chapter's `fund_balance_cents` or a member's `good_standing`) each count as a mutation of the affected resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.6. Nested Resource Retrieval and Validation Order

The API is deeply nested: a service hour entry lives under a member who lives under a chapter, and an application lives under a cycle under a chapter. For any request whose path contains multiple resource identifiers, the server validates identifiers strictly left to right. The first identifier that does not correspond to an existing resource — or that exists but is not nested under the previously resolved parent — terminates the request with `ERR_NOT_FOUND` (HTTP 404); the server never reports a deeper identifier's problem while a shallower one is unresolved.

Beyond existence, every request is evaluated against a fixed validation order. Authentication comes first (a missing or unrecognized role or user header yields `ERR_UNAUTHENTICATED`), then role authorization for the endpoint (`ERR_UNAUTHORIZED`), then the left-to-right existence and nesting check (`ERR_NOT_FOUND`), then the chapter freeze guard of §2.7 (`ERR_CHAPTER_FROZEN`), then the target resource's state-machine legality (`ERR_INVALID_STATE`, HTTP 409, raised whenever a transition is attempted from a state that does not permit it). Only after all of those pass are the business rules of §3 evaluated, in the domain-specific order stated with each workflow; where several business checks guard one endpoint, §3 states their relative order explicitly. Independently of all of the above, a malformed request payload or a missing required field is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The same `ERR_INVALID_REQUEST` (HTTP 400) rejects a field value that fails a stated field rule — an enum outside its permitted set (`grade_level`, `semester`, `office`, `reason_code`, `outcome`, `priority`), a numeric floor such as the fundraiser goal minimum or the dues amount's strictly-positive rule, or a timestamp that cannot be parsed — while an identifier supplied in a request body (for example `cycle_id` on election creation or `called_by_officer_id` on minutes) that does not resolve to an existing resource of the chapter is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.7. The Chapter Freeze Guard

A chapter's own status acts as a circuit breaker over everything beneath it. While a chapter is `SUSPENDED` or `DISSOLVED`, every mutating request nested under that chapter — any create or action endpoint below the chapter's path — is rejected with `ERR_CHAPTER_FROZEN` (HTTP 409). Suspension freezes the member-facing surface in a specific, enumerated way: no new `ServiceHourEntry`, `FundraiserRequest`, `OfficerElection`, or `CycleApplication` may be created while the freeze holds. Reinstatement lifts the freeze. The freeze guard is evaluated before any state-machine or business rule, per the validation order in §2.6.

### 2.8. Precision, Money, and Rounding

All monetary amounts in the system are integers of cents: fundraiser goals and costs, ledger amounts, dues amounts, the fund balance, and dues arrears are all whole numbers of cents with no fractional part. Ledger `amount_cents` values are signed — a positive amount credits the chapter and a negative amount debits it. Where the ledger roll-up sums entries, each entry is already stored as integer cents; the sum is taken over those integers directly, with no fractional accumulation rounded at the end.

Grade point averages are carried with two decimal places by convention — `weighted_gpa` on the 5.0 scale and `unweighted_gpa` on the 4.0 scale — and are stored exactly as supplied, with no scale-range or decimal-place validation performed by the server. The eligibility score described in §3.2 is a decimal value rounded half-up to exactly two decimal places. Service hours are recorded in quarter-hour increments: an entry's `hours` must be an exact multiple of 0.25.

### 2.9. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control against their parent aggregate, and each carries its own stale-version error identity:

- **Advisor approval of a fundraiser request** requires the request body to carry `expected_chapter_version`, holding the chapter `version` the client last observed. If the chapter's current `version` does not match — because, for example, another writer has recorded a ledger entry that legitimately advanced the chapter's fiscal posture since the client read it — the approval is rejected with `ERR_STALE_CHAPTER_VERSION` (HTTP 412), preventing the advisor from approving against a fund balance they never saw. A successful approval itself advances the chapter's `version` by one.
- **Dismissal of a member** requires `expected_member_version` matching the member's current `version`. A member whose `version` has advanced since the client last read it — for instance because a probation case resolution legitimately changed the member's strike count and standing — cannot be dismissed on that stale view; the rejection carries `ERR_STALE_MEMBER_VERSION` (HTTP 412). A successful dismissal advances the member's `version` by one.
- **Induction of a membership cycle** requires `expected_cycle_version` matching the cycle's current `version`. If another writer has approved or rejected an application since the client read the cycle — legitimately changing the cycle's candidate pool — the induction is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412). A successful induction advances the cycle's `version` by one.

These stale-version rejections belong to the `ERR_STALE_VERSION` family catalogued in §5: a mismatched parent `version` on an OCC-guarded write is always an HTTP 412 rejection, reported with the endpoint-specific identifier above. No endpoint outside these three accepts a version field; optimistic locking is not optional-but-available elsewhere — it simply does not apply.

## 3. Business Logic & Workflows

### 3.1. Chartering a Chapter and Managing Its Lifecycle

An `ActivitiesDirector` charters a new chapter by supplying the school's `school_name`, the national `charter_number` (recorded as supplied; the server does not enforce its uniqueness), the `advisor_user_id` of the faculty advisor who will run it, the eligibility thresholds `gpa_threshold_weighted` and `gpa_threshold_unweighted`, the service requirements `service_hours_annual_required` and `service_hours_per_semester_required`, and the `national_dues_cents_per_member` owed to the national office each year per active member. A freshly created chapter begins in `DRAFT` status with `standing` of `GOOD_STANDING`, a `fund_balance_cents` of zero, `dues_arrears_cents` of zero, an `active_member_count` of zero, and `version` 1. The `active_member_count` always counts precisely the chapter's members in `ACTIVE` status. A chapter's `status` moves among `DRAFT`, `ACTIVE`, `SUSPENDED`, and the terminal `DISSOLVED`.

Activation is the chapter's gate to operation, and it validates the charter's internal consistency before anything else can happen. The `ActivitiesDirector` may move a chapter from `DRAFT` to `ACTIVE` only when `advisor_user_id` is non-empty, when `gpa_threshold_weighted` is at least `gpa_threshold_unweighted` (the weighted bar may not sit below the unweighted bar), and when `service_hours_annual_required` is at least twice `service_hours_per_semester_required` (two semesters must be able to sum to the annual floor); failure of any of these consistency checks — like attempting the transition from any status other than `DRAFT` — is rejected with `ERR_INVALID_STATE` (HTTP 409). Upon activation the chapter's `standing` is set to `GOOD_STANDING`.

A chapter's `standing` is a derived posture, recomputed whenever dues arrears, member standings, or probation volumes change, and it takes one of `GOOD_STANDING`, `PROBATIONARY`, or `REVOKED`. The derivation runs as an ordered ladder. If `dues_arrears_cents` exceeds thirty times the chapter's `national_dues_cents_per_member`, the standing is `REVOKED`. Otherwise, if any arrears are owed at all — `dues_arrears_cents` greater than zero — the standing is `PROBATIONARY`. Otherwise the member base is examined: when the chapter has at least one `ACTIVE` member and twice the number of members in `ON_PROBATION` exceeds the number of `ACTIVE` members, the standing is `PROBATIONARY`. In every remaining case the standing is `GOOD_STANDING`. An advisor or the director can read the full posture through the chapter standing view, which reports `standing`, `dues_arrears_cents`, `fund_balance_cents`, and `active_member_count` together.

Suspension and dissolution sit at the director's level. Moving a chapter from `ACTIVE` to `SUSPENDED` has no further precondition, but it engages the freeze guard of §2.7: members in `ACTIVE` or `ON_PROBATION` are frozen in place, and no new service hour entry, fundraiser request, election, or cycle application may be created until the freeze lifts. Reinstatement from `SUSPENDED` back to `ACTIVE` is permitted only once every probation case under the chapter that was left `OPEN` has been `RESOLVED`; reinstatement lifts the freeze. Dissolution is the terminal act: a chapter may move from `ACTIVE` to `DISSOLVED` only when its `fund_balance_cents` is exactly zero, when every member has reached `ALUMNUS` or `DISMISSED`, and when no officer election remains in `DRAFT`, `OPEN`, or `TALLIED`. Dissolution cascades: every officer role still standing moves to `REMOVED`, and every fundraiser request still in `DRAFT`, `SUBMITTED`, `ADVISOR_APPROVED`, or `DIRECTOR_APPROVED` is swept to `REJECTED`.

### 3.2. The Membership Cycle: Nomination, Review, and Induction

Before any cycle can run, the chapter needs a roster. The advisor — or the activities director — registers each prospective member with the school-issued `student_id`, the student's `full_name` and `email`, a `grade_level` of 9, 10, 11, or 12, and both grade point averages: `weighted_gpa` on the 5.0 scale and `unweighted_gpa` on the 4.0 scale, each carried to two decimal places. A newly registered student begins in `PROSPECTIVE` status, unattached to any cycle, with `inducted_cycle_id` null; as noted in §3.3, such a member's `good_standing` starts false. A member's `status` walks among `PROSPECTIVE`, `CANDIDATE`, `ACTIVE`, `ON_PROBATION`, and the terminal pair `DISMISSED` and `ALUMNUS`.

Membership intake itself runs in cycles. An `Advisor` creates a membership cycle under a chapter by supplying a `cycle_label` (for example `2026-FALL`), an `academic_year` (for example `2026-2027`), a `semester` of `FALL` or `SPRING`, and three dates: `nomination_open_date`, `nomination_close_date`, and `induction_date`. A new cycle begins in `PLANNED` with an empty `candidate_member_ids` and an `inducted_count` of zero; a cycle's `status` walks among `PLANNED`, `NOMINATION`, `REVIEW`, `INDUCTED`, and the terminal pair `CLOSED` and `CANCELLED`.

Creation enforces three guards, evaluated in this order so that the most structural problem surfaces first. First, the single-active-cycle guard: at most one cycle per chapter may exist in `PLANNED`, `NOMINATION`, `REVIEW`, or `INDUCTED` at a time; a second live cycle is rejected with `ERR_ACTIVE_CYCLE_EXISTS` (HTTP 409). Second, the calendar must be coherent: `nomination_open_date` must fall strictly before `nomination_close_date`, which must fall strictly before `induction_date`, and cycle transitions must honor the current logical clock; violations are rejected with `ERR_INVALID_CYCLE_DATE` (HTTP 422). Third, the labels must be well-formed: `cycle_label` must be a four-digit year, a hyphen, and either `FALL` or `SPRING`, and `academic_year` must be two four-digit years joined by a hyphen; malformed labels are rejected with `ERR_INVALID_FORMAT` (HTTP 422).

Opening nominations moves a cycle from `PLANNED` to `NOMINATION`. The chapter must be `ACTIVE`, the chapter's `current_cycle_id` must be null or point at a `CLOSED` or `CANCELLED` cycle, and the logical clock must have reached `nomination_open_date` — an attempt to open early is rejected with `ERR_INVALID_CYCLE_DATE`. When nominations open, the chapter's `current_cycle_id` is set to this cycle.

With nominations open, an `Advisor` nominates a `PROSPECTIVE` student for the current cycle. Nomination evaluates its guards in a fixed order: first the posture checks — the chapter must be `ACTIVE` and the chapter's `current_cycle_id` must point at a cycle currently in `NOMINATION`, with violations surfacing as `ERR_INVALID_STATE`; then the scheduling check — the student must have no `ACTIVE` athletics calendar block overlapping the cycle's `induction_date`, or the nomination is rejected with `ERR_ATHLETICS_CONFLICT` (HTTP 409); and only then the academic check — the student's `weighted_gpa` must be at least the chapter's `gpa_threshold_weighted`, or their `unweighted_gpa` must be at least the chapter's `gpa_threshold_unweighted`, with failure on both scales rejected as `ERR_GPA_BELOW_THRESHOLD` (HTTP 422). A nominee who would fail both the scheduling and the academic checks therefore hears about the athletics conflict first. A successful nomination advances the member from `PROSPECTIVE` to `CANDIDATE` and, in the same act, creates a `CycleApplication` under the current cycle in `SUBMITTED` status, recording the applying student as `member_id` and the nominating advisor's identity as `nominated_by_user_id`; the nomination response returns the updated member object.

Closing nominations — permitted once the logical clock has reached `nomination_close_date`, with an early attempt rejected as `ERR_INVALID_CYCLE_DATE` — requires a non-empty candidate pool; closing with no candidates is rejected with `ERR_EMPTY_CANDIDATE_POOL` (HTTP 409). The close moves the cycle from `NOMINATION` to `REVIEW` and cascades every `SUBMITTED` application to `UNDER_REVIEW`. That cascade is the moment each application's `eligibility_score` is computed.

The `eligibility_score` is a five-component weighted score, evaluated in a pinned order: every sub-score is computed first, and the weighted sum is taken last. The GPA component expresses the member's `weighted_gpa` as a percentage of the 5.0 scale — the GPA divided by 5.0 and multiplied by 100 — clamps the result into the inclusive range from 0 to 100, and weights it at 40 percent. The service component divides the member's `verified_service_hours_current_year` by twice the chapter's `service_hours_annual_required`, multiplies by 100, clamps into the same 0-to-100 range, and weights it at 30 percent (a chapter whose doubled annual requirement is zero contributes a service sub-score of 100 when the member has any verified hours this year, else 0). The leadership component contributes 50 points when the member currently holds an active office (`is_officer` is true) and 0 points otherwise, weighted at 15 percent. The probation component subtracts 20 points for each of the member's `probation_strikes`, weighted at 10 percent. The athletics component subtracts 10 points when an `ACTIVE` athletics block belonging to the member overlaps the cycle's `induction_date`, and 0 otherwise, weighted at 5 percent. The five weighted components are summed, the raw total is clamped into the inclusive range from 0 to 100, and the result is rounded half-up to two decimal places to yield the final `eligibility_score`.

During review, the advisor decides each `UNDER_REVIEW` application. Approval is granted only when the application's `eligibility_score` is at least 70.00 and the member's `good_standing` flag — as defined in §3.3 — is true, and a failure on either front is rejected with `ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD` (HTTP 422). The athletics-conflict guard also applies at approval time, and the evaluation order on approval is state legality first, then the athletics check (`ERR_ATHLETICS_CONFLICT`), then the score and standing check. Rejection requires the advisor to supply a `rejection_reason` and moves the application to `REJECTED`; the rejected student returns from `CANDIDATE` to `PROSPECTIVE`, rejoining the pool for a future cycle. The applicant may also withdraw their own `UNDER_REVIEW` application: withdrawal is a member-self operation, so the caller's `X-User-ID` must be the `id` of the applying member — anyone else is rejected with `ERR_MEMBER_MISMATCH` (HTTP 403) — and a successful withdrawal moves the application to `WITHDRAWN` and returns the member to `PROSPECTIVE`.

Induction is the cycle's climax, and it is one of the three OCC-guarded writes of §2.9. The advisor's induction request must carry `expected_cycle_version` equal to the cycle's current `version`; a stale view — for instance, one taken before a colleague rejected a final application — is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412). Beyond the version check, the logical clock must have reached `induction_date` — a premature induction is rejected with `ERR_INVALID_CYCLE_DATE` — and every application under the cycle must already rest in `APPROVED`, `REJECTED`, `INDUCTED`, or `WITHDRAWN` — not a single application may remain `UNDER_REVIEW`. The evaluation order is state legality first, then the calendar check, then version freshness. A successful induction moves the cycle from `REVIEW` to `INDUCTED`, sweeps every `APPROVED` application to `INDUCTED`, advances each such applicant's member record from `CANDIDATE` to `ACTIVE` with `inducted_cycle_id` set to this cycle, recomputes the chapter's `active_member_count`, and advances the cycle's `version` by one. The cycle's `inducted_count` always reflects how many members carry its `id` in their `inducted_cycle_id`, and `candidate_member_ids` always reflects the members whose application points at this cycle while they remain `CANDIDATE`.

A cycle closes from `INDUCTED` once every officer election tied to its `cycle_id` has reached `CERTIFIED` or `VOIDED` — and, independently, the cycle must have produced at least one `INDUCTED` application before it may close, else the close is rejected with `ERR_NO_INDUCTED_APPLICATIONS` (HTTP 409); the election check is evaluated first, as a state-legality matter, and the inducted-application check second. Closing moves the cycle to `CLOSED` and clears the chapter's `current_cycle_id` if it still points at this cycle. A cycle may instead be cancelled outright, but only from `PLANNED`; cancellation moves it to `CANCELLED` and likewise clears `current_cycle_id` if needed.

### 3.3. Service Hours and Member Standing

Service is the chapter's ongoing obligation, and every hour is verified before it counts. A service hour entry can be logged by the member themselves, by an officer, or by the advisor; the log captures `activity_name`, the `service_date` on which the work occurred, the `hours` worked, the host `organization`, and a `supervisor_email` contact. The entry is born in `PENDING_VERIFICATION`. Two field rules guard the log at creation: `hours` must be greater than zero, no more than 12, and an exact multiple of 0.25 — anything else is rejected with `ERR_INVALID_SERVICE_HOURS` (HTTP 422) — and `service_date` must not lie in the future relative to the logical clock, else the log is rejected with `ERR_FUTURE_SERVICE_DATE` (HTTP 422).

Verification is the advisor's desk. Moving an entry from `PENDING_VERIFICATION` to `VERIFIED` requires the chapter to be `ACTIVE` and the member to be in `ACTIVE` or `ON_PROBATION`; the entry's `hours` are re-validated against the same greater-than-zero, at-most-12, quarter-hour rule (`ERR_INVALID_SERVICE_HOURS`), and the `service_date` must not sit after the current logical clock. These checks are evaluated state-first: a frozen or wrong-state target surfaces `ERR_CHAPTER_FROZEN` or `ERR_INVALID_STATE` before the hours rule is consulted, and the hours rule is consulted before the date rule. A successful verification stamps `verified_by_user_id` with the verifying advisor's identity and recomputes the member's two service aggregates: `verified_service_hours_current_year`, the sum of `hours` across the member's `VERIFIED` entries in the current academic year, and `verified_service_hours_current_semester`, the same sum restricted to the current semester. The member's `good_standing` is then recomputed as well. Rejection of a pending entry requires a `rejection_reason` and moves it to `REJECTED`; the member's aggregates and `good_standing` are recomputed, though the totals do not change since the entry never counted. Voiding works from either non-terminal side: a `PENDING_VERIFICATION` entry may be voided without precondition, while voiding a `VERIFIED` entry additionally requires the chapter's `standing` to be anything other than `REVOKED` — and because a voided verified entry stops counting, both service aggregates and `good_standing` are recomputed. `VERIFIED`, `REJECTED`, and `VOID` are the entry's terminal states.

Two compliance readings sit on top of the verified totals, and the system keeps them deliberately distinct. The **annual-cumulative** reading asks only whether `verified_service_hours_current_year` is at least the chapter's `service_hours_annual_required`; it is the good-standing rule used for fundraising and dues-remittance purposes. The **per-semester-strict** reading additionally requires `verified_service_hours_current_semester` to be at least the chapter's `service_hours_per_semester_required`; it is reported, alongside the annual reading, by the member standing view. The two diverge precisely when a member's hours are unevenly distributed: a member carrying 20 verified hours this year but only 2 this semester, against requirements of 15 annually and 6 per semester, passes the annual reading and fails the strict one. The member standing view exposes both readings side by side, returning `good_standing`, `verified_service_hours_current_year`, `verified_service_hours_current_semester`, `probation_strikes`, `annual_cumulative_compliant`, and `per_semester_strict_compliant` in a single payload.

A member's `good_standing` flag distills the whole compliance picture: it is always false while the member is `PROSPECTIVE` or `DISMISSED`; it is false whenever the member has a probation case resting in `OPEN` or `APPEALED`; for a member in `ACTIVE` or `ON_PROBATION` it additionally requires satisfying the service-hour requirement under the annual-cumulative reading; and in every remaining case — a `CANDIDATE` or an `ALUMNUS` with no open case — it is true. A freshly registered prospective member starts with `good_standing` false.

### 3.4. Officer Elections, Roles, and Meeting Minutes

Officer elections run under a cycle. The advisor creates an election by naming its `cycle_id` and the `office` being contested — one of `PRESIDENT`, `VICE_PRESIDENT`, `SECRETARY`, `TREASURER`, or `HISTORIAN` — and the election begins in `DRAFT`. Its `status` ranges over `DRAFT`, `OPEN`, `TALLIED`, and the terminal pair `CERTIFIED` and `VOIDED`.

Opening an election moves it from `DRAFT` to `OPEN` and is guarded by three checks in order. State first: the chapter must be `ACTIVE`. Then the scheduling guard: the athletics-conflict rule of §3.8 applies to election scheduling just as it does to nomination and application approval — the open scans every member of the chapter and is rejected with `ERR_ATHLETICS_CONFLICT` when any of them has an `ACTIVE` athletics block overlapping the referenced cycle's `induction_date`. Finally, election singularity: no other election for the same chapter may be in `OPEN` or `TALLIED` at that moment, else the open is rejected with `ERR_ELECTION_ALREADY_OPEN` (HTTP 409). Opening also requires the referenced cycle to be in `REVIEW` or `INDUCTED`, and it stamps `opened_at`.

Voting belongs to the members. A member casts a vote by naming `voter_member_id` — themselves, with a mismatch rejected as `ERR_MEMBER_MISMATCH` (HTTP 403) — and `candidate_member_id`; the vote is recorded with a server-stamped `cast_at` and a `status` of `CAST`. Both the voter and the candidate must reference existing members of the chapter, else the cast is rejected with `ERR_NOT_FOUND` (HTTP 404). Two guards protect the ballot box: the election must be `OPEN` at the moment of casting, else the vote is rejected with `ERR_INVALID_VOTE_STATE` (HTTP 409), and each voter may hold at most one vote in `CAST` status in a given election — a repeat attempt being rejected with `ERR_DUPLICATE_VOTE` (HTTP 409), while an earlier vote swept to `VOIDED` no longer counts against the limit.

Tallying moves the election from `OPEN` to `TALLIED` and requires at least one vote in `CAST`; tallying an empty ballot box is rejected with `ERR_NO_VOTES_CAST` (HTTP 409). The tally counts the `CAST` votes per candidate. If a single candidate holds the highest count, that member's `id` becomes `winner_member_id` and `runoff_required` is set to false. If two or more candidates share the top count, `winner_member_id` is null and `runoff_required` is true — a tie is a tie, and vote timestamps are never consulted to break one. Tallying stamps `tallied_at`.

Certification moves the election from `TALLIED` to `CERTIFIED`, and its two guards are evaluated in a pinned order. First, office occupancy: at most one `ACTIVE` officer role may exist per chapter and office, so if the contested office is already held, certification is rejected with `ERR_OFFICE_ALREADY_OCCUPIED` (HTTP 409). Second, decisiveness: `runoff_required` must be false and `winner_member_id` must be non-null, else the certification is rejected with `ERR_RUNOFF_REQUIRED` (HTTP 409) and the chapter must run a runoff instead. A successful certification creates an `OfficerRole` for the winning member: the role records the election's `id` in `election_id`, the winner in `member_id`, and the contested `office` denormalized onto the role; it begins in `ACTIVE` with `started_at` stamped, and the winner's `is_officer` flag is recomputed to true.

An election may also be voided — from `DRAFT`, from `OPEN`, or from `TALLIED` — moving it to `VOIDED`. Only a void from `OPEN` has fallout: every vote still in `CAST` beneath the election is swept to `VOIDED`.

Office holders exit in two ways. Resignation is self-service: the caller's `X-User-ID` must correspond to the `member_id` recorded on the role, and a caller who does not hold the role is rejected with `ERR_NOT_AN_OFFICER` (HTTP 403). Resignation moves the role from `ACTIVE` to `RESIGNED`, stamps `ended_at`, and recomputes the member's `is_officer`. Removal is the advisor's instrument and is permitted only when the office-holding member is no longer `ACTIVE`; it moves the role to `REMOVED`, stamps `ended_at`, and recomputes `is_officer` the same way. An `is_officer` flag is true exactly when the member holds at least one role in `ACTIVE`.

Minutes keep the chapter's deliberations auditable. Any officer may draft meeting minutes, supplying the `meeting_date`, the `called_by_officer_id` of the officer who called the meeting, the `attendees_member_ids` of those present, an `agenda`, and the `notes` body; a draft rests in `DRAFT`. The drafting caller must hold an `ACTIVE` officer role in the chapter, else `ERR_NOT_AN_OFFICER` (HTTP 403), and `called_by_officer_id` must identify an existing `OfficerRole` of the chapter, else `ERR_NOT_FOUND` (HTTP 404). Submission is the secretary's exclusive privilege: moving minutes from `DRAFT` to `SUBMITTED` requires the caller to hold an `ACTIVE` officer role whose `office` is `SECRETARY` — any other caller is rejected with `ERR_NOT_AN_OFFICER` — and the officer recorded in `called_by_officer_id` must still hold an `ACTIVE` role, a lapse surfacing as `ERR_INVALID_STATE`. Submission records the secretary in `submitted_by_officer_id`. The advisor then approves submitted minutes, moving them to `APPROVED` and recording themselves in `approved_by_user_id`. Approval is not the end of the road: a secretary may amend approved minutes, provided the new `notes` differ from the prior body — an identical body is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and amendment moves the minutes from `APPROVED` to `AMENDED` — from which the system immediately returns them to `SUBMITTED` once the amended body is saved, cycling them back through advisor approval. Minutes thus live in a loop among `DRAFT`, `SUBMITTED`, `APPROVED`, and `AMENDED`, with `APPROVED` as the only resting state that represents a ratified record.

### 3.5. The Activity Fund: Fundraisers and the Ledger

Fundraising begins with an officer. The officer drafts a fundraiser request with a `title`, a `description` of its purpose, a `goal_amount_cents` target of at least 100 cents, an `upfront_cost_cents` of zero or more that the chapter must front, the `requested_by_officer_id` of the sponsoring officer, and a `scheduled_date`. The drafting caller must hold an `ACTIVE` officer role in the chapter, else `ERR_NOT_AN_OFFICER` (HTTP 403); a goal below 100 cents or a negative upfront cost is rejected with `ERR_INVALID_REQUEST` (HTTP 400); and `requested_by_officer_id` must identify an existing `OfficerRole` of the chapter, else `ERR_NOT_FOUND` (HTTP 404). The request is born in `DRAFT`; its `status` walks among `DRAFT`, `SUBMITTED`, `ADVISOR_APPROVED`, `DIRECTOR_APPROVED`, `EXECUTED`, and the terminal pair `CLOSED` and `REJECTED`.

Submission moves the request from `DRAFT` to `SUBMITTED` and carries three preconditions, state legality evaluated before the fiscal one: the sponsoring officer's role must be `ACTIVE`, the chapter must be `ACTIVE`, and the chapter's `fund_balance_cents` must be at least the request's `upfront_cost_cents` — a chapter may never commit to front money it does not have, and an overcommitted request is rejected with `ERR_INSUFFICIENT_CHAPTER_FUNDS` (HTTP 409).

Approval is a two-rung ladder with a segregation-of-duties wall between the rungs. The first rung is the advisor's, and it is OCC-guarded per §2.9: the approval must carry `expected_chapter_version` matching the chapter's current `version`, and a stale view — one that predates, say, a freshly recorded ledger entry — is rejected with `ERR_STALE_CHAPTER_VERSION` (HTTP 412). State legality is evaluated before version freshness, so a request that is not `SUBMITTED` hears `ERR_INVALID_STATE` even if the version is also stale. A successful advisor approval moves the request to `ADVISOR_APPROVED`, records the advisor in `advisor_approved_by_user_id`, and advances the chapter's `version` by one. The second rung belongs to the `ActivitiesDirector`, who must not be the same identity as the advisor recorded on the first rung: a director approval whose `X-User-ID` equals `advisor_approved_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 409). A successful director approval moves the request to `DIRECTOR_APPROVED` and records the director in `director_approved_by_user_id`; the request's `segregation_of_duties_enforced` flag is a derived invariant that is true exactly when the two recorded approver identities differ. Rejection can intercede from either rung — the advisor may reject a `SUBMITTED` request, and the director may reject an `ADVISOR_APPROVED` one — moving it to `REJECTED`.

Execution converts approval into money. Once the logical clock has reached the `scheduled_date`, an officer records the event's actuals by supplying `actual_gross_cents` — an attempt before the `scheduled_date` is rejected with `ERR_INVALID_STATE` (HTTP 409); the system computes `actual_net_cents` as the gross receipts minus the request's `upfront_cost_cents`, and the request moves from `DIRECTOR_APPROVED` to `EXECUTED`. Execution writes the ledger: a `FundLedgerEntry` of type `FUNDRAISER_DEPOSIT` is created with `amount_cents` equal to the net proceeds and a status of `PENDING`, and, when the fronted cost was greater than zero, a second entry of type `UPFRONT_COST_DISBURSEMENT` is created with `amount_cents` equal to the negated upfront cost and a status of `CLEARED`.

Closing is the fundraiser's final act, from `EXECUTED` to `CLOSED`, and the advisor may close only once the deposit has actually landed: the ledger entry tied to this fundraiser via `fundraiser_id` with type `FUNDRAISER_DEPOSIT` must be `CLEARED`, else the close is rejected with `ERR_DEPOSIT_NOT_CLEARED` (HTTP 409). Closing recomputes the chapter's `fund_balance_cents`.

The ledger itself is the chapter's single fiscal source of truth. Each entry records an optional `fundraiser_id` (null for entries not born of a fundraiser), an `entry_type` — one of `FUNDRAISER_DEPOSIT`, `UPFRONT_COST_DISBURSEMENT`, `DUES_REMITTANCE`, `NATIONAL_DUES_PAYMENT`, or `ADJUSTMENT` — a signed `amount_cents`, an `entry_date`, and a free-text `description`. Entries are born in `PENDING` and rest terminally in `CLEARED` or `VOIDED`. The advisor clears a pending entry — only while the chapter is `ACTIVE` — and clearing recomputes the chapter's `fund_balance_cents`; when the cleared entry is a `NATIONAL_DUES_PAYMENT`, the chapter's `dues_arrears_cents` is recomputed as well. Voiding a pending entry likewise recomputes the balance. The balance rule itself is exact: `fund_balance_cents` is the sum of `amount_cents` over precisely the chapter's entries in `CLEARED` status — `PENDING` entries are excluded, and since every amount is stored as integer cents, no rounding arises anywhere in the roll-up.

### 3.6. National Dues, Remittance, and Chapter Arrears

Every active member owes the national office the chapter's `national_dues_cents_per_member` each academic year, and the payment pipeline has three stages. A dues payment is first recorded — by the member, an officer, or the advisor — with the `academic_year` it covers, an `amount_cents` strictly greater than zero, and the `paid_at` timestamp of payment; the record rests in `PENDING_REMITTANCE`. Its `status` ranges over `PENDING_REMITTANCE`, `REMITTED`, `REFUNDED`, and `VOID`.

Remittance is the advisor forwarding the money onward, and it is guarded twice: the paying member must be in `ACTIVE` or `ON_PROBATION`, and the chapter's `fund_balance_cents` must be at least the payment's `amount_cents` — the chapter remits from real funds, and a shortfall is rejected with `ERR_INSUFFICIENT_FUNDS_FOR_REMITTANCE` (HTTP 409). Remittance stamps `remitted_at`, moves the payment to `REMITTED`, and writes the ledger in the same act: a `FundLedgerEntry` of type `NATIONAL_DUES_PAYMENT` is created with `amount_cents` equal to the negated payment amount and a status of `CLEARED`. Both chapter roll-ups — `fund_balance_cents` and `dues_arrears_cents` — are then recomputed.

Two escape hatches exist. A payment still in `PENDING_REMITTANCE` may be voided to `VOID` without further precondition. A payment already `REMITTED` may be refunded, but only once the paying member has reached `DISMISSED`; the refund moves the payment to `REFUNDED` and writes a compensating ledger entry of type `ADJUSTMENT` with `amount_cents` equal to the payment amount credited back, in `CLEARED` status, after which both chapter roll-ups are again recomputed.

The arrears figure keeps the national office's ledger view of the chapter. The chapter's expected obligation is `national_dues_cents_per_member` multiplied by its `active_member_count`; the member count used is the chapter's currently recorded `active_member_count` at the moment of recomputation, and within the recomputation pipeline the member count is always computed before the arrears figure that consumes it. The chapter's remitted total is the sum of `amount_cents` across its dues payments for the current academic year whose status is `REMITTED`. The `dues_arrears_cents` is the expected obligation minus the remitted total, floored at zero — arrears never run negative. This arrears figure feeds the standing ladder of §3.1: any arrears at all make the chapter at least `PROBATIONARY`, and arrears beyond thirty members' worth of dues revoke the chapter's standing entirely.

### 3.7. Probation, Appeals, and Member Exit

Standards enforcement begins when the advisor opens a probation case against a member, supplying their own identity as `opened_by_user_id`, a `reason_code` of `GPA_BELOW_THRESHOLD`, `SERVICE_HOURS_SHORTFALL`, `CONDUCT_VIOLATION`, or `MISSED_MEETINGS`, and the narrative `evidence_text`. The case is born in `OPEN` with `opened_at` stamped, and its `status` moves among `OPEN`, `APPEALED`, and the terminal pair `RESOLVED` and `DISMISSED`.

The member may appeal an `OPEN` case. Appeal is a member-self operation — the caller's `X-User-ID` must be the `id` of the member under review, else the appeal is rejected with `ERR_MEMBER_MISMATCH` (HTTP 403) — and it is time-boxed: the appeal must arrive strictly before fourteen days have elapsed since `opened_at`, as measured by the logical clock; a late appeal is rejected with `ERR_APPEAL_WINDOW_CLOSED` (HTTP 409). A timely appeal moves the case to `APPEALED`. The identity check is evaluated before the window check.

Resolution belongs to the advisor, from either `OPEN` or `APPEALED`, and requires an `outcome`. When the outcome is `STANDARDS_VIOLATION_CONFIRMED`, the resolution must also carry a `probation_end_date` lying strictly after the current logical clock; a missing `outcome`, an unrecognized `outcome`, a missing `probation_end_date`, or a `probation_end_date` not strictly in the future is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Resolution stamps `resolved_by_user_id`, moves the case to `RESOLVED`, and cascades according to the outcome. On a confirmed violation the member moves from `ACTIVE` to `ON_PROBATION` and their `probation_strikes` — the count of their `RESOLVED` cases bearing a confirmed outcome — increases by one; should that count thereby reach at least two, the member is cascaded onward to `DISMISSED` with the full dismissal side effects described below. Whether confirmed or not, the member's `good_standing` is recomputed at resolution. An outcome of `STANDARDS_VIOLATION_NOT_CONFIRMED` leaves the member's status untouched. Alternatively the advisor may dismiss the case without prejudice from either `OPEN` or `APPEALED`: the case moves to `DISMISSED` and its `outcome` is set to `STANDARDS_VIOLATION_NOT_CONFIRMED`.

A member serving probation earns their way back through reinstatement, which moves them from `ON_PROBATION` to `ACTIVE`. Reinstatement requires that no probation case for the member rest in `OPEN` or `APPEALED`, and that the logical clock have passed the `probation_end_date` of every one of the member's resolved cases whose outcome was confirmed; the member's `good_standing` is recomputed on reinstatement.

Dismissal is the heaviest act in the system and one of the three OCC-guarded writes of §2.9. The dismissal request must carry `expected_member_version` matching the member's current `version`; a stale view — for instance, one read before a colleague resolved the member's latest case — is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412). When dismissing from `ACTIVE`, cause is additionally required: either the member's `probation_strikes` have reached at least two, or the advisor supplies an explicit `override_reason`; a causeless dismissal is rejected with `ERR_DISMISSAL_REQUIRES_CAUSE` (HTTP 422). When the member already rests in `ON_PROBATION`, the dismissal rests on the version check alone. The checks are evaluated state first, then cause, then version freshness. However reached, dismissal cascades broadly: every officer role the member holds in `ACTIVE` moves to `REMOVED`, every service hour entry of theirs still in `PENDING_VERIFICATION` is swept to `VOID`, every vote they cast that remains in `CAST` is swept to `VOIDED`, and the chapter's `active_member_count` is recomputed. `DISMISSED` is terminal.

Graduation is the kinder exit. A member in `ACTIVE` or `ON_PROBATION` whose `grade_level` is 12 may be graduated to `ALUMNUS` by the advisor; the cascade resigns rather than removes — every officer role they hold in `ACTIVE` moves to `RESIGNED` — and the chapter's `active_member_count` is recomputed. `ALUMNUS` is terminal.

### 3.8. Athletics Calendar Coordination

Student athletes owe their teams time, and the chapter must schedule around those commitments rather than collide with them. An advisor or the activities director registers an athletics calendar block for a member by supplying the `member_id`, the `block_start` and `block_end` of the commitment, the `sport`, and a `priority` of `PRACTICE`, `GAME`, or `TOURNAMENT`. The block is born `ACTIVE` and may later be cancelled to `CANCELLED`. One field rule guards registration: `block_start` must fall strictly before `block_end`; an inverted or zero-length block is rejected with `ERR_INVALID_ATHLETICS_BLOCK` (HTTP 422).

Blocks are half-open intervals. A block covers the instant of its `block_start` and every instant up to but not including its `block_end`; consequently two intervals conflict exactly when each begins before the other ends, and two blocks that merely touch — one ending at the precise instant the other begins — do not conflict. A member has an athletics conflict with a given date when an `ACTIVE` block of theirs covers that date: the block's start falls on or before the date and its end falls strictly after it. When several `ACTIVE` blocks cover the same date, the highest-priority block governs: `TOURNAMENT` outranks `GAME`, which outranks `PRACTICE`.

The conflict rule reaches into three workflows already described. Nomination of a prospective member is rejected with `ERR_ATHLETICS_CONFLICT` when one of the nominee's `ACTIVE` blocks overlaps the cycle's `induction_date`; the same overlap drives the athletics penalty inside the `eligibility_score` of §3.2, costing the application ten weighted-at-five-percent points. Approval of an application under review applies the same guard. And opening an officer election is subject to it as well: an open is rejected with `ERR_ATHLETICS_CONFLICT` (HTTP 409) when any member of the chapter has an `ACTIVE` block overlapping the referenced cycle's `induction_date`, as pinned in §3.4. In every case the check consults only `ACTIVE` blocks — a `CANCELLED` block commits nobody.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`, as do all reads. The table below is a summary only — request payloads, response shapes, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (default `2026-08-01T00:00:00Z`) | ActivitiesDirector |
| POST | `/chapters` | Create a chapter (initial status `DRAFT`) | ActivitiesDirector |
| GET | `/chapters` | List chapters with pagination | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/chapters/{chapterId}` | Fetch a chapter | ActivitiesDirector, Advisor, Officer, Member |
| POST | `/chapters/{chapterId}/activate` | Activate a chapter | ActivitiesDirector |
| POST | `/chapters/{chapterId}/suspend` | Suspend a chapter (freezes child mutations) | ActivitiesDirector |
| POST | `/chapters/{chapterId}/reinstate` | Reinstate a suspended chapter | ActivitiesDirector |
| POST | `/chapters/{chapterId}/dissolve` | Dissolve a chapter | ActivitiesDirector |
| GET | `/chapters/{chapterId}/standing` | Fetch the chapter standing rollup | ActivitiesDirector, Advisor |
| POST | `/chapters/{chapterId}/members` | Register a prospective member | Advisor, ActivitiesDirector |
| GET | `/chapters/{chapterId}/members` | List members of a chapter | ActivitiesDirector, Advisor, Officer |
| GET | `/chapters/{chapterId}/members/{memberId}` | Fetch a member | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/chapters/{chapterId}/members/{memberId}/standing` | Fetch member standing detail | ActivitiesDirector, Advisor |
| POST | `/chapters/{chapterId}/members/{memberId}/nominate` | Nominate a `PROSPECTIVE` member for the current cycle | Advisor |
| POST | `/chapters/{chapterId}/members/{memberId}/reinstate` | Reinstate an `ON_PROBATION` member to `ACTIVE` | Advisor |
| POST | `/chapters/{chapterId}/members/{memberId}/dismiss` | Dismiss a member (OCC-guarded) | Advisor |
| POST | `/chapters/{chapterId}/members/{memberId}/graduate` | Graduate a member to `ALUMNUS` | Advisor |
| POST | `/chapters/{chapterId}/membership-cycles` | Create a membership cycle | Advisor |
| GET | `/chapters/{chapterId}/membership-cycles` | List membership cycles | ActivitiesDirector, Advisor, Officer |
| GET | `/chapters/{chapterId}/membership-cycles/{cycleId}` | Fetch a membership cycle | ActivitiesDirector, Advisor, Officer, Member |
| POST | `/chapters/{chapterId}/membership-cycles/{cycleId}/open-nominations` | Open the cycle for nominations | Advisor |
| POST | `/chapters/{chapterId}/membership-cycles/{cycleId}/close-nominations` | Close nominations and cascade applications to review | Advisor |
| POST | `/chapters/{chapterId}/membership-cycles/{cycleId}/induct` | Induct the cycle (OCC-guarded) | Advisor |
| POST | `/chapters/{chapterId}/membership-cycles/{cycleId}/close` | Close the cycle | Advisor |
| POST | `/chapters/{chapterId}/membership-cycles/{cycleId}/cancel` | Cancel the cycle | Advisor |
| GET | `/chapters/{chapterId}/membership-cycles/{cycleId}/applications` | List applications under a cycle | ActivitiesDirector, Advisor, Officer |
| GET | `/chapters/{chapterId}/membership-cycles/{cycleId}/applications/{applicationId}` | Fetch an application | ActivitiesDirector, Advisor, Officer, Member |
| POST | `/chapters/{chapterId}/membership-cycles/{cycleId}/applications/{applicationId}/approve` | Approve an `UNDER_REVIEW` application | Advisor |
| POST | `/chapters/{chapterId}/membership-cycles/{cycleId}/applications/{applicationId}/reject` | Reject an `UNDER_REVIEW` application | Advisor |
| POST | `/chapters/{chapterId}/membership-cycles/{cycleId}/applications/{applicationId}/withdraw` | Withdraw an application (member self) | Member |
| POST | `/chapters/{chapterId}/members/{memberId}/service-hour-entries` | Log a service hour entry | Member, Officer, Advisor |
| GET | `/chapters/{chapterId}/members/{memberId}/service-hour-entries` | List service hour entries for a member | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/chapters/{chapterId}/members/{memberId}/service-hour-entries/{entryId}` | Fetch a service hour entry | ActivitiesDirector, Advisor, Officer, Member |
| POST | `/chapters/{chapterId}/members/{memberId}/service-hour-entries/{entryId}/verify` | Verify a service hour entry | Advisor |
| POST | `/chapters/{chapterId}/members/{memberId}/service-hour-entries/{entryId}/reject` | Reject a service hour entry | Advisor |
| POST | `/chapters/{chapterId}/members/{memberId}/service-hour-entries/{entryId}/void` | Void a service hour entry | Advisor |
| POST | `/chapters/{chapterId}/elections` | Create an officer election | Advisor |
| GET | `/chapters/{chapterId}/elections` | List officer elections | ActivitiesDirector, Advisor, Officer |
| GET | `/chapters/{chapterId}/elections/{electionId}` | Fetch an officer election | ActivitiesDirector, Advisor, Officer, Member |
| POST | `/chapters/{chapterId}/elections/{electionId}/open` | Open the election for voting | Advisor |
| POST | `/chapters/{chapterId}/elections/{electionId}/tally` | Tally the votes | Advisor |
| POST | `/chapters/{chapterId}/elections/{electionId}/certify` | Certify the election and create the officer role | Advisor |
| POST | `/chapters/{chapterId}/elections/{electionId}/void` | Void the election | Advisor |
| POST | `/chapters/{chapterId}/elections/{electionId}/votes` | Cast a vote | Member |
| GET | `/chapters/{chapterId}/elections/{electionId}/votes` | List votes for an election | ActivitiesDirector, Advisor |
| GET | `/chapters/{chapterId}/officer-roles` | List officer roles | ActivitiesDirector, Advisor, Officer |
| GET | `/chapters/{chapterId}/officer-roles/{roleId}` | Fetch an officer role | ActivitiesDirector, Advisor, Officer, Member |
| POST | `/chapters/{chapterId}/officer-roles/{roleId}/resign` | Officer resigns (self) | Officer |
| POST | `/chapters/{chapterId}/officer-roles/{roleId}/remove` | Advisor removes an officer | Advisor |
| POST | `/chapters/{chapterId}/meeting-minutes` | Create meeting minutes | Officer |
| GET | `/chapters/{chapterId}/meeting-minutes` | List meeting minutes | ActivitiesDirector, Advisor, Officer |
| GET | `/chapters/{chapterId}/meeting-minutes/{minutesId}` | Fetch meeting minutes | ActivitiesDirector, Advisor, Officer, Member |
| POST | `/chapters/{chapterId}/meeting-minutes/{minutesId}/submit` | Submit minutes (Secretary only) | Officer |
| POST | `/chapters/{chapterId}/meeting-minutes/{minutesId}/approve` | Advisor approves minutes | Advisor |
| POST | `/chapters/{chapterId}/meeting-minutes/{minutesId}/amend` | Amend approved minutes (cycles back to `SUBMITTED`) | Officer |
| POST | `/chapters/{chapterId}/fundraiser-requests` | Create a fundraiser request | Officer |
| GET | `/chapters/{chapterId}/fundraiser-requests` | List fundraiser requests | ActivitiesDirector, Advisor, Officer |
| GET | `/chapters/{chapterId}/fundraiser-requests/{fundraiserId}` | Fetch a fundraiser request | ActivitiesDirector, Advisor, Officer, Member |
| POST | `/chapters/{chapterId}/fundraiser-requests/{fundraiserId}/submit` | Submit a fundraiser request | Officer |
| POST | `/chapters/{chapterId}/fundraiser-requests/{fundraiserId}/advisor-approve` | Advisor approves fundraiser (OCC-guarded) | Advisor |
| POST | `/chapters/{chapterId}/fundraiser-requests/{fundraiserId}/director-approve` | Director approves fundraiser (segregation of duties) | ActivitiesDirector |
| POST | `/chapters/{chapterId}/fundraiser-requests/{fundraiserId}/reject` | Reject a fundraiser | Advisor, ActivitiesDirector |
| POST | `/chapters/{chapterId}/fundraiser-requests/{fundraiserId}/execute` | Record fundraiser execution with actuals | Officer |
| POST | `/chapters/{chapterId}/fundraiser-requests/{fundraiserId}/close` | Close the fundraiser | Advisor |
| GET | `/chapters/{chapterId}/fund-ledger-entries` | List ledger entries | ActivitiesDirector, Advisor, Officer |
| GET | `/chapters/{chapterId}/fund-ledger-entries/{entryId}` | Fetch a ledger entry | ActivitiesDirector, Advisor, Officer |
| POST | `/chapters/{chapterId}/fund-ledger-entries/{entryId}/clear` | Clear a ledger entry | Advisor |
| POST | `/chapters/{chapterId}/fund-ledger-entries/{entryId}/void` | Void a ledger entry | Advisor |
| POST | `/chapters/{chapterId}/members/{memberId}/dues-payments` | Record a dues payment from a member | Member, Officer, Advisor |
| GET | `/chapters/{chapterId}/members/{memberId}/dues-payments` | List dues payments for a member | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/chapters/{chapterId}/members/{memberId}/dues-payments/{paymentId}` | Fetch a dues payment | ActivitiesDirector, Advisor, Officer, Member |
| POST | `/chapters/{chapterId}/members/{memberId}/dues-payments/{paymentId}/remit` | Remit dues to the national office | Advisor |
| POST | `/chapters/{chapterId}/members/{memberId}/dues-payments/{paymentId}/void` | Void a dues payment | Advisor |
| POST | `/chapters/{chapterId}/members/{memberId}/dues-payments/{paymentId}/refund` | Refund a remitted dues payment (member must be `DISMISSED`) | Advisor |
| POST | `/chapters/{chapterId}/members/{memberId}/probation-cases` | Open a probation case | Advisor |
| GET | `/chapters/{chapterId}/members/{memberId}/probation-cases` | List probation cases for a member | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/chapters/{chapterId}/members/{memberId}/probation-cases/{caseId}` | Fetch a probation case | ActivitiesDirector, Advisor, Officer, Member |
| POST | `/chapters/{chapterId}/members/{memberId}/probation-cases/{caseId}/appeal` | Member appeals a probation case | Member |
| POST | `/chapters/{chapterId}/members/{memberId}/probation-cases/{caseId}/resolve` | Resolve a probation case | Advisor |
| POST | `/chapters/{chapterId}/members/{memberId}/probation-cases/{caseId}/dismiss-case` | Dismiss a probation case without prejudice | Advisor |
| POST | `/chapters/{chapterId}/athletics-blocks` | Register an athletics calendar block for a member | Advisor, ActivitiesDirector |
| GET | `/chapters/{chapterId}/athletics-blocks` | List athletics blocks | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/chapters/{chapterId}/athletics-blocks/{blockId}` | Fetch an athletics block | ActivitiesDirector, Advisor, Officer, Member |
| POST | `/chapters/{chapterId}/athletics-blocks/{blockId}/cancel` | Cancel an athletics block | Advisor, ActivitiesDirector |
| GET | `/members/{memberId}` | Fetch a member by id (flat form) | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/members` | Flat list of members with FK filters | ActivitiesDirector, Advisor |
| GET | `/membership-cycles/{cycleId}` | Fetch a membership cycle by id (flat form) | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/membership-cycles` | Flat list of membership cycles with FK filters | ActivitiesDirector, Advisor |
| GET | `/cycle-applications/{applicationId}` | Fetch an application by id (flat form) | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/cycle-applications` | Flat list of applications with FK filters | ActivitiesDirector, Advisor |
| GET | `/service-hour-entries/{entryId}` | Fetch a service hour entry by id (flat form) | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/service-hour-entries` | Flat list of service hour entries with FK filters | ActivitiesDirector, Advisor |
| GET | `/officer-elections/{electionId}` | Fetch an officer election by id (flat form) | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/officer-elections` | Flat list of officer elections with FK filters | ActivitiesDirector, Advisor |
| GET | `/election-votes/{voteId}` | Fetch an election vote by id (flat form) | ActivitiesDirector, Advisor |
| GET | `/election-votes` | Flat list of election votes with FK filters | ActivitiesDirector, Advisor |
| GET | `/officer-roles/{roleId}` | Fetch an officer role by id (flat form) | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/officer-roles` | Flat list of officer roles with FK filters | ActivitiesDirector, Advisor |
| GET | `/meeting-minutes/{minutesId}` | Fetch meeting minutes by id (flat form) | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/meeting-minutes` | Flat list of meeting minutes with FK filters | ActivitiesDirector, Advisor |
| GET | `/fundraiser-requests/{fundraiserId}` | Fetch a fundraiser request by id (flat form) | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/fundraiser-requests` | Flat list of fundraiser requests with FK filters | ActivitiesDirector, Advisor |
| GET | `/fund-ledger-entries/{entryId}` | Fetch a ledger entry by id (flat form) | ActivitiesDirector, Advisor, Officer |
| GET | `/fund-ledger-entries` | Flat list of ledger entries with FK filters | ActivitiesDirector, Advisor |
| GET | `/dues-payments/{paymentId}` | Fetch a dues payment by id (flat form) | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/dues-payments` | Flat list of dues payments with FK filters | ActivitiesDirector, Advisor |
| GET | `/probation-cases/{caseId}` | Fetch a probation case by id (flat form) | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/probation-cases` | Flat list of probation cases with FK filters | ActivitiesDirector, Advisor |
| GET | `/athletics-blocks/{blockId}` | Fetch an athletics block by id (flat form) | ActivitiesDirector, Advisor, Officer, Member |
| GET | `/athletics-blocks` | Flat list of athletics blocks with FK filters | ActivitiesDirector, Advisor |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue enumerates only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_FORMAT` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CHAPTER_FROZEN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_STALE_CHAPTER_VERSION` | 412 |
| `ERR_STALE_MEMBER_VERSION` | 412 |
| `ERR_STALE_CYCLE_VERSION` | 412 |
| `ERR_ATHLETICS_CONFLICT` | 409 |
| `ERR_INVALID_ATHLETICS_BLOCK` | 422 |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 409 |
| `ERR_GPA_BELOW_THRESHOLD` | 422 |
| `ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD` | 422 |
| `ERR_INVALID_SERVICE_HOURS` | 422 |
| `ERR_FUTURE_SERVICE_DATE` | 422 |
| `ERR_ACTIVE_CYCLE_EXISTS` | 409 |
| `ERR_INVALID_CYCLE_DATE` | 422 |
| `ERR_EMPTY_CANDIDATE_POOL` | 409 |
| `ERR_NO_INDUCTED_APPLICATIONS` | 409 |
| `ERR_INSUFFICIENT_CHAPTER_FUNDS` | 409 |
| `ERR_INSUFFICIENT_FUNDS_FOR_REMITTANCE` | 409 |
| `ERR_ELECTION_ALREADY_OPEN` | 409 |
| `ERR_OFFICE_ALREADY_OCCUPIED` | 409 |
| `ERR_NO_VOTES_CAST` | 409 |
| `ERR_RUNOFF_REQUIRED` | 409 |
| `ERR_DEPOSIT_NOT_CLEARED` | 409 |
| `ERR_NOT_AN_OFFICER` | 403 |
| `ERR_MEMBER_MISMATCH` | 403 |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 |
| `ERR_DISMISSAL_REQUIRES_CAUSE` | 422 |
| `ERR_DUPLICATE_VOTE` | 409 |
| `ERR_INVALID_VOTE_STATE` | 409 |
