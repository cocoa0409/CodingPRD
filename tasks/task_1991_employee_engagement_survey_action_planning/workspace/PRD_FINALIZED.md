# Engagement Survey API — Product Requirements Document

## 1. Introduction

Employee engagement measurement fails in two familiar ways: survey programs that collect responses nobody acts on, and reporting pipelines that leak enough detail to identify individual respondents. This document specifies the Engagement Survey API, a platform for an HR people analytics team that treats confidentiality and follow-through as first-class design constraints rather than afterthoughts. The API governs the full arc of an engagement program — building a reusable question bank, standing up census and pulse survey cycles against the organizational roster, driving response rates through a disciplined reminder cadence, distributing results to line managers under strict minimum-group-size suppression, converting insight into tracked action plans, and finally linking survey outcomes back to attrition and performance records so the program's predictive value can be quantified.

The platform serves five constituencies with deliberately separated powers. HR operations staff own the instrument, the roster, and cycle orchestration, but are barred from scoring the very cycles they created. People analysts own scoring, benchmarks, reminder sweeps, and outcome linkage, but may not author survey content. Line managers see only their own organizational subtree, only after results are published, and only at aggregate level; individual answers are never exposed to them. Employees answer only their own invitations. Executives consume published results read-only. All resources are mounted under the `/engagement` prefix, and all time-dependent behavior is driven by a logical clock that the platform controls explicitly — a requirement made precise in §2.5.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The platform recognizes exactly five roles: `HRAdmin`, `PeopleAnalyst`, `UnitManager`, `EmployeeRole`, and `Executive`. A request missing either header, or presenting a role the platform does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted on the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `HRAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does, however, record the creating `HRAdmin`'s `X-User-ID` on each survey cycle so the segregation-of-duties check in §2.7 can compare it later. When `X-User-Role` is `PeopleAnalyst` or `Executive`, `X-User-ID` is likewise an opaque operator identifier that the server never compares to any entity's `id`.

When `X-User-Role` is `UnitManager`, the caller's identity is backed by the `OrgUnit` entity: `X-User-ID` is matched against the `manager_user_id` recorded on organizational units, and the units whose `manager_user_id` equals `X-User-ID` — together with all of their descendant units — define the manager's own unit subtree. Every ownership check on action plans, action items, and report snapshots ultimately compares the relevant unit's `manager_user_id` to `X-User-ID`. When `X-User-Role` is `EmployeeRole`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` compare the resource's `employee_id` field to `X-User-ID`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items from the start of the result set and defaults to 0; it must not be negative. A `limit` outside the permitted range, a negative `offset`, or any query parameter the endpoint does not declare is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Nearly every resource in the platform carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is an ISO 8601 UTC timestamp refreshed on every modification. `version` is an integer that starts at 1 and increments by exactly 1 on every mutation of the resource — including cascaded mutations triggered by a child resource, such as the survey cycle's `version` advancing when an item is pinned into it, and derived-field recomputes such as `response_rate`, `progress_pct`, or `attrition_risk` changing value.

Three resource types are deliberately lighter: a survey response, an outcome linkage row, and a reminder event each carry only `id` and `created_at`. On those three, both `updated_at` and `version` are absent — they are immutable records written once and never edited in place.

Every lifecycle-bearing resource — item banks, survey items, survey cycles, invitations, benchmark sets, action plans, and action items — exposes its current state through a `status` field whose value is always one of the exact state strings named in §3; employees carry their roster state on `employment_status` instead.

### 2.5. The Logical Clock and Survey Windows

All time-dependent behavior — window enforcement, reminder cadence, tenure gating, overdue plan detection, and automatic transitions — is evaluated against a **logical clock** maintained by the server, never against wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never drifts or falls back to real time on its own. An admin-only test-driving capability advances the clock: an `HRAdmin` supplies a `to_iso8601` instant, the server adopts it as the current logical time, and the response reports the new `current_utc`. Setting the clock may cause system auto-transitions whose time preconditions now hold to fire — in particular the automatic close of a survey cycle whose close instant has been reached.

Two window conventions recur throughout this document. A survey cycle's field window opens at `opens_at` (inclusive) and ends at `closes_at` (exclusive), and `closes_at` must be strictly after `opens_at`. Plan and milestone deadlines are checked against the cycle's close: an action plan's `due_at` must be strictly after the cycle's `closes_at`, and a milestone's `target_at` must be no later than its plan's `due_at`. Violations of these temporal rules are rejected with `ERR_WINDOW_VIOLATION` (HTTP 422).

### 2.6. Respondent Confidentiality and Minimum-N Suppression

Confidentiality is the platform's founding constraint. A `UnitManager` may read report snapshots only for units inside their own subtree — the units whose `manager_user_id` matches their `X-User-ID`, plus every descendant unit — and only after the cycle's results have been published. A `UnitManager` may never read an individual survey response under any circumstances. Violations of these boundaries — reaching for a snapshot outside the manager's subtree, requesting suppressed scores, or attempting response-level access — are rejected with `ERR_CONFIDENTIALITY` (HTTP 403). A manager-facing snapshot read attempted while the cycle is still being scored — snapshots exist but are unpublished — is rejected with `ERR_SNAPSHOT_NOT_PUBLISHED` (HTTP 409).

Scores are additionally gated by group size. Every organizational unit carries a `min_n_threshold` (defaulting to 5, and always between 3 and 20 inclusive) and a `verbatim_n_threshold` (defaulting to 10). When a snapshot's submitted-response count is strictly less than the effective minimum, the snapshot is numerically suppressed: its dimension map and overall score are withheld. When the count is strictly less than the effective verbatim threshold, verbatim comments are withheld. A count exactly at a threshold is visible — suppression begins one response below it. The mechanics of suppression are specified fully in §3.5.

### 2.7. Segregation of Duties

Instrument authorship, cycle orchestration, and scoring are deliberately separated. The `HRAdmin` operator who created a survey cycle may not perform the scoring transition on that same cycle; the attempt is rejected with `ERR_DUTY_SEGREGATION` (HTTP 403). Symmetrically, a `PeopleAnalyst` may not create item banks or add survey items to a bank; those write operations, when attempted by a `PeopleAnalyst`, are likewise rejected with `ERR_DUTY_SEGREGATION`. The rule applies to exactly three operations: cycle scoring, item-bank creation, and survey-item creation.

### 2.8. Validation Order and Rule Precedence

When several checks could reject the same request, the platform evaluates them in a fixed order so the surfaced error is deterministic. Request-shape validation runs first: required body fields present, field types valid, enum members legal, and numeric ranges honored — failures yield `ERR_VALIDATION` (HTTP 400) — together with the query-envelope check on list endpoints, where a `limit` outside 1 through 100, a negative `offset`, or an unknown query parameter yields `ERR_INVALID_REQUEST`. Body fields the endpoint does not declare are ignored, never rejected: a client-supplied system or derived field (for example `id`, `version`, `invited_count`, or `response_rate`) carried in a request body has no effect, and unknown-identifier rejection applies to query parameters only. Next comes authentication (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of the resources named in the URL, validated left to right (`ERR_NOT_FOUND`), then existence of entity identifiers referenced in the request body — `bank_id`, `item_id`, `unit_id`, `employee_id`, `cycle_id`, `plan_id` — which surface as `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

Only after the request is well-formed, authenticated, authorized, and fully resolved does the platform consult the state machines: an action that the target resource's current state does not permit is rejected with `ERR_INVALID_STATE` (HTTP 409), so an illegal transition always surfaces as a state error rather than being masked by a business rule. Business-safety checks follow: confidentiality (`ERR_CONFIDENTIALITY`), plan ownership (`ERR_PLAN_OWNERSHIP`), the publish gate (`ERR_SNAPSHOT_NOT_PUBLISHED`), and segregation of duties (`ERR_DUTY_SEGREGATION`). After safety come the business constraints, in this order: uniqueness violations (`ERR_DUPLICATE`), window violations (`ERR_WINDOW_VIOLATION`), reminder-cadence handling for the bulk sweep, the unit-tree acyclicity check (`ERR_UNIT_CYCLE`), the threshold-inversion check (`ERR_THRESHOLD_INVERSION`), the single-open-cycle invariant (`ERR_CYCLE_ALREADY_OPEN`), and item-count sufficiency (`ERR_INSUFFICIENT_ITEMS`). The optimistic-concurrency check (`ERR_STALE_VERSION`) runs last, so a stale write is reported only after every other constraint has passed.

### 2.9. Nested Resource Retrieval

For any endpoint whose URL contains multiple resource identifiers, the platform validates existence strictly left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. A request aimed at an item within a bank that does not exist fails on the bank before the item is ever consulted; the same discipline applies to invites within cycles, items within plans, and outcome linkages within employees. Identifiers referenced in a request body rather than the path are validated immediately afterward and surface as `ERR_REFERENCE_NOT_FOUND` when missing, per the ordering in §2.8.

### 2.10. Hierarchical Consistency and Cascading Mutation

The platform maintains consistency across its hierarchies automatically. Pinning an item into a survey cycle, or adding an item to a bank, increments the parent's `version` by 1 and refreshes its `updated_at`. Retiring an item bank retires every still-active item it owns. Closing a survey cycle expires every invitation that was never answered. Resolving a milestone recomputes its plan's progress and may complete the plan outright; abandoning a plan drops its remaining milestones. Invite submissions and expirations recompute the cycle's derived counters and `response_rate`. Each of these cascades mutates the parent resource and therefore carries the `updated_at` and `version` consequences of §2.4 wherever a version increment is stated in §3. The server performs these reconciliations on its own initiative whenever their criteria are satisfied, without requiring a client request aimed at the affected parent.

### 2.11. Scoring Precision and Rounding

All rounding in the platform uses the round-half-up method. Dimension scores and overall engagement scores are stored at exactly 2 decimal places; the intermediate per-answer weighted products feeding them are computed at 4 decimal places. Response rates and the attrition risk index are stored at 4 decimal places. Benchmark percentiles are stored at 2 decimal places. A survey item's `weight` is a positive decimal with exactly one fractional digit, at least 0.1 and at most 5.0. A cycle's `sampling_ratio` carries at most 2 decimal places, is strictly greater than 0, and at most 1.0. Derived counts produced by flooring — pulse-sample invite targets and action-plan progress percentages — round down to the nearest integer.

### 2.12. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both reject a writer whose view of the parent resource is stale. First, configuring a survey cycle requires the request to carry `expected_cycle_version`, holding the cycle's `version` as the client last observed it; if the cycle's current `version` has advanced since then — for example because another writer pinned or removed a cycle item, which bumps the cycle's `version` as a cascade — the configure is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from committing a configuration against items it never saw. Second, submitting an action plan requires `expected_plan_version` carrying the plan's last observed `version`; if the plan's `version` has advanced — for example because a reviewer's rejection landed after the manager's last read — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412). Both fields are non-optional on their respective operations. No other endpoint takes a version field.

## 3. Business Logic & Workflows

### 3.1. Building the Instrument: Item Banks and Survey Items

The survey instrument begins as an **item bank** created by an `HRAdmin` with a `name` — a human-readable label that must be non-empty and unique per tenant — and a `framework` identifying the question family, one of `EWI`, `Q12`, or `CUSTOM`. A new bank starts in `DRAFT` status.

Items join the bank one at a time. Each survey item is created under a bank (the owning bank is identified by the request, and the item's `bank_id` records it) with a stable `item_code` such as EWI-01 that must be unique within its bank, a `dimension` classifying the item into one of the six engagement dimensions — `PURPOSE`, `GROWTH`, `MANAGER_SUPPORT`, `BELONGING`, `WORKLOAD`, or `RECOGNITION` — and a scoring `weight` per the precision rules of §2.11. An item may optionally carry a verbatim comment prompt, recorded through `has_free_text`, which defaults to false when omitted. New items start in `ACTIVE` status. Every item added increments the bank's `version` by 1.

Activation is the gate that makes a bank usable: an `HRAdmin` activates a `DRAFT` bank, moving it to `ACTIVE`, only when the bank holds at least three survey items in `ACTIVE` status; a thinner instrument is rejected with `ERR_INSUFFICIENT_ITEMS` (HTTP 422). Activation increments the bank's `version` by 1.

Retirement moves an `ACTIVE` bank to `RETIRED`, its terminal state. Retirement is refused while any survey cycle built on this bank sits in `CONFIGURED`, `OPEN`, or `SCORING` status — an in-flight cycle keeps its instrument alive. When retirement succeeds, every item of the bank still in `ACTIVE` status flips to `RETIRED` alongside it, and the bank's `version` increments by 1. Consistent with §2.7, a `PeopleAnalyst` attempting to create a bank or add an item is rejected with `ERR_DUTY_SEGREGATION` even before content rules apply, and a duplicate `item_code` within one bank is rejected with `ERR_DUPLICATE` (HTTP 409).

### 3.2. The Organizational Roster: Units, Managers, and Employees

Reporting and action planning are organized around the **organizational unit** tree. An `HRAdmin` creates a unit with a `name`, the `manager_user_id` of the `UnitManager` who will own its reports and plans, and optionally a `parent_unit_id`; the root unit is the one created with no parent, and `parent_unit_id` may be null only there. The tree must remain acyclic — neither creating a unit nor updating one later may set a `parent_unit_id` that would close a cycle in the tree, and such attempts are rejected with `ERR_UNIT_CYCLE` (HTTP 422). Each unit also carries the confidentiality thresholds of §2.6: `min_n_threshold` defaults to 5 and must lie between 3 and 20 inclusive, while `verbatim_n_threshold` defaults to 10 and must never be lower than the unit's own `min_n_threshold`; an inverted pair is rejected with `ERR_THRESHOLD_INVERSION` (HTTP 422) both at creation and on update. Updating a unit's thresholds or parent increments its `version` by 1.

Employees form the respondent population. An `HRAdmin` registers each employee with an `external_ref` — the unique HRIS reference, where a duplicate is rejected with `ERR_DUPLICATE` — the `unit_id` of their current unit, an `employment_status` of `ACTIVE`, `LEAVE`, or `TERMINATED`, and a `hired_at` timestamp that later gates census eligibility. `exited_at` starts as null and is stamped when employment ends: terminating an employee moves `employment_status` to `TERMINATED`, records the supplied `exited_at`, and increments the employee's `version` by 1. Only employees in `ACTIVE` status are ever invited to a survey; those on `LEAVE` and those `TERMINATED` are excluded from every eligibility sweep.

### 3.3. Composing and Opening a Survey Cycle

A survey cycle is created by an `HRAdmin` in `DRAFT` status, carrying a `label` such as "2026 Census", a `cycle_kind` of `CENSUS` or `PULSE`, the `bank_id` of the instrument it draws from, and the window bounds `opens_at` and `closes_at`. Two cycle-wide knobs tune reporting and reach: `min_n_default` (default 5, between 3 and 20 inclusive) is the cycle-wide minimum-group fallback, and `sampling_ratio` (default 1.0) is the fraction of the eligible population a pulse cycle will invite. The cycle tracks its own traction through derived counters — `invited_count`, `submitted_count`, `partial_count`, and the computed `response_rate` — plus an `attrition_risk` figure that remains null until scoring begins.

Before a cycle can be configured, the `HRAdmin` pins items into it. Pinning an item creates a cycle item carrying the `cycle_id`, the source `item_id`, a `pinned_weight`, and a `display_order`. The `pinned_weight` is a snapshot of the survey item's `weight` taken at selection time; later edits to the item's weight do not disturb it. `display_order` is a 1-based presentation index unique within the cycle, and a given item may be pinned into the same cycle only once — a repeated `display_order` or a repeated `item_id` within one cycle is rejected with `ERR_DUPLICATE`. Each pin increments the cycle's `version` by 1.

Configuration moves the cycle `DRAFT → CONFIGURED`. Three conditions must hold: the cycle has at least three pinned cycle items (otherwise `ERR_INSUFFICIENT_ITEMS`), `closes_at` is strictly after `opens_at` (a violation is `ERR_WINDOW_VIOLATION`, per §2.5), and the linked item bank is in `ACTIVE` status. Configuration is one of the two OCC-guarded writes of §2.12: the request must carry `expected_cycle_version`, and a mismatch against the cycle's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful configure increments the cycle's `version` by 1.

Opening moves the cycle `CONFIGURED → OPEN` and is the moment the respondent population crystallizes. The logical clock must have reached `opens_at`, and no other cycle may currently be in `OPEN` status — the platform admits exactly one open cycle at a time, and a second open attempt is rejected with `ERR_CYCLE_ALREADY_OPEN` (HTTP 409). The instant a cycle opens, an eligibility sweep runs. The eligible population is every employee with `employment_status` `ACTIVE` whose `hired_at` falls on or before the date thirty days before the cycle's `opens_at` — a tenure gate that excludes brand-new hires. For a `CENSUS` cycle the sweep invites the entire eligible population and `sampling_ratio` is ignored. For a `PULSE` cycle the sweep multiplies the eligible headcount by `sampling_ratio`, rounds the product down to a whole number, and invites exactly that many employees, chosen in order of earliest `hired_at` first with ties broken by earliest `created_at`. Each chosen employee receives an invitation in `INVITED` status whose `unit_id_at_invite` snapshots the employee's `unit_id` at sweep time, so later transfers never re-attribute responses. The cycle's `invited_count` is then recomputed, and its `version` increments by 1.

### 3.4. The Field Period: Invitations, Reminders, and Response Capture

Once a cycle is `OPEN`, each invitation lives a small lifecycle of its own. An employee holding an invitation in `INVITED` or `REMINDED` status may submit a complete response, moving the invitation to `SUBMITTED`; may submit a partial response, moving it to `PARTIAL`; and may later upgrade a `PARTIAL` invitation to `SUBMITTED` by completing the remaining items. Every submission is personal: the caller's `X-User-ID` must equal the invitation's `employee_id`, and a mismatch is rejected with `ERR_INVITE_OWNERSHIP` (HTTP 403). An employee reading back their own invitation or their own response row is subject to the same ownership comparison.

The submission payload is the `answers` array, one entry per pinned cycle item, each entry naming the `cycle_item_id`, an integer `score` from 1 to 5, and an optional `comment` string for items flagged `has_free_text`. A complete submission must cover every cycle item of the cycle; a partial submission must answer at least one item while leaving at least one unanswered. A complete submission with missing items, or a partial submission that is empty or actually complete, is rejected with `ERR_ANSWERS_INCOMPLETE` (HTTP 422). Timing is enforced twice over: submitting against a cycle that is no longer `OPEN` is a state error rejected with `ERR_INVALID_STATE`, while submitting at or after `closes_at` violates the field window and is rejected with `ERR_WINDOW_VIOLATION`.

A complete submission writes the survey response row with `is_partial` false, stamps the invitation's `submitted_at`, adds 1 to the cycle's `submitted_count`, and recomputes the cycle's `response_rate`. A partial submission writes the response row with `is_partial` true and instead adds 1 to `partial_count`, again recomputing `response_rate`. Upgrading from `PARTIAL` to `SUBMITTED` replaces the existing response row with a complete one (`is_partial` false), moves 1 from `partial_count` to `submitted_count`, and recomputes the rate. Each invitation carries exactly one response row set — the response's `invite_id` is unique per invitation — and every one of these transitions increments the invitation's `version` by 1. Response rows are readable by `HRAdmin`, `PeopleAnalyst`, and the owning employee — never by a `UnitManager`, for whom any response-level access attempt is rejected with `ERR_CONFIDENTIALITY`.

Reminders follow a disciplined cadence managed by a `PeopleAnalyst`-driven bulk sweep over the cycle's unanswered invitations. An invitation in `INVITED` status becomes `REMINDED` when all of the following hold: the cycle is `OPEN`; the invitation's `reminder_count` is below the cap of three; and either the invitation has never been reminded and at least twenty-four hours have elapsed since the cycle opened, or at least forty-eight hours have elapsed since `last_reminded_at`. An invitation already in `REMINDED` status is reminded again under the same rules — cap below three, and at least forty-eight hours elapsed since `last_reminded_at`. Each successful reminder appends a reminder event recording `sent_at` and the next 1-based `sequence_no` for that invitation, increments `reminder_count` by 1, stamps `last_reminded_at` with the current logical time, and increments the invitation's `version` by 1. Invitations blocked by the cap or the cadence are not errors — the sweep simply skips them and returns success with `reminded_count` and `reminded_invite_ids` reflecting the reminders actually sent. Running the sweep against a cycle that is not `OPEN`, by contrast, is rejected with `ERR_INVALID_STATE`.

### 3.5. Close, Scoring, and Confidentiality-Gated Reporting

A cycle leaves the field in one of two ways: an `HRAdmin` closes it deliberately at any time after opening, or the system closes it automatically once the logical clock reaches `closes_at`. Either path moves the cycle `OPEN → CLOSED`. At close, every invitation still in `INVITED` or `REMINDED` status flips to `EXPIRED`; invitations in `PARTIAL` status remain `PARTIAL` and continue to count at half weight in the response rate. The cycle's `response_rate` is recomputed — the rate is the sum of `submitted_count` plus half of `partial_count`, divided by the number of employees invited, rounded half-up to 4 decimal places. Expired invitations remain in the denominator because those employees were invited; `invited_count` is frozen at cycle close, and a cycle in which nobody was ever invited has a null `response_rate`. Closing increments the cycle's `version` by 1.

Scoring moves the cycle `CLOSED → SCORING` and belongs to the `PeopleAnalyst` — with the §2.7 caveat that the `HRAdmin` who created the cycle may not be the one to score it, on pain of `ERR_DUTY_SEGREGATION`. Scoring generates a **report snapshot** for every organizational unit that received at least one invitation in the cycle, in two scopes apiece: `DIRECT`, covering only invitees attributed to the unit itself via `unit_id_at_invite`, and `SUBTREE`, covering the unit plus all descendant units. Each snapshot records its `cycle_id`, `unit_id`, `scope`, the `submitted_n` count of submitted invitations in scope, a `dimension_scores` map, an `overall_score`, a `benchmark_percentile`, the suppression flags `numeric_suppressed` and `verbatim_suppressed`, and a `generation` counter that starts at 1. A snapshot may later be recomputed — a `PeopleAnalyst` re-runs suppression and scoring on it — which bumps `generation` by 1 and increments the snapshot's `version` by 1. Scoring itself increments the cycle's `version` by 1.

The engagement score itself is computed as follows, and the evaluation order is pinned. Only invitations in `SUBMITTED` status feed the scores; partial responses are excluded entirely, not half-weighted. For each answer of each submitted invitation in scope, the raw `score` from 1 to 5 is first rescaled onto a 0-to-100 scale by subtracting 1 and multiplying by 25; the rescaled value is then multiplied by the pinned weight of the answered item, and that per-answer product is rounded half-up to 4 decimal places. A dimension's score is the sum of those 4-decimal products over all answers belonging to items of that dimension, divided by the sum of the pinned weights of that dimension's items — the weight denominator counted once per submitted respondent — rounded half-up to 2 decimal places. The overall score is the sum of the 4-decimal products over all answers, divided by the total pinned weight of all items counted once per submitted respondent, likewise rounded half-up to 2 decimal places — and it is computed from the unrounded 4-decimal products, never from the already-rounded dimension means. For a `PULSE` cycle every pinned weight is treated as 1.0 regardless of the stored value, so identical answers yield a different overall score under pulse scoring than under census scoring, where the stored per-item weights apply.

Suppression then gates visibility per §2.6. The effective minimum is the unit's own `min_n_threshold` — the unit override always wins, and the cycle's `min_n_default` is unused whenever the unit row exists, which it always does — and the effective verbatim threshold is the unit's `verbatim_n_threshold`. `numeric_suppressed` is true exactly when `submitted_n` is strictly less than the effective minimum, counting only `SUBMITTED` invitations; a suppressed snapshot exposes an empty `dimension_scores` map and a null `overall_score`. `verbatim_suppressed` is true exactly when `submitted_n` is strictly less than the effective verbatim threshold, and verbatim comments are served only when `verbatim_suppressed` is false.

Publication moves the cycle `SCORING → REPORTED`, provided every snapshot of the cycle has reached `generation` at least 1, and increments the cycle's `version` by 1. Publication is the moment managers gain access: from `REPORTED` onward a `UnitManager` may read snapshots within their own subtree. Before publication — while the cycle is `SCORING` and snapshots exist but are unpublished — a manager-facing snapshot read is refused with `ERR_SNAPSHOT_NOT_PUBLISHED`; reads outside the manager's subtree, and any manager attempt at response-level access, remain `ERR_CONFIDENTIALITY` regardless of cycle state.

Archiving is the cycle's terminal move, `REPORTED → ARCHIVED`, performed by an `HRAdmin` once every action plan belonging to the cycle has reached `COMPLETED` or `ABANDONED`; an outstanding plan blocks archival with `ERR_INVALID_STATE`. Archival increments the cycle's `version` by 1.

### 3.6. Benchmarks and Percentile Comparison

A `PeopleAnalyst` registers a **benchmark set** — a reference distribution such as "Tech Industry 2026" — with a `name` and a `dimension_scores` array holding at least five reference overall scores, each between 0 and 100 inclusive at 2 decimal places; a thinner distribution is rejected with `ERR_BENCHMARK_TOO_SMALL` (HTTP 422). A new benchmark set starts in `ACTIVE` status and remains usable until a `PeopleAnalyst` retires it, moving it to `RETIRED` and incrementing its `version` by 1; retired sets are excluded from percentile computation.

When scoring runs with an `ACTIVE` benchmark set linked, each snapshot's `benchmark_percentile` is the snapshot's standing against that distribution: count the reference scores strictly below the snapshot's `overall_score`, add half the count of reference scores exactly equal to it, divide by the total number of reference scores, multiply by 100, and round half-up to 2 decimal places. The percentile is null whenever the snapshot is numerically suppressed or no `ACTIVE` benchmark set exists.

### 3.7. From Insight to Action: Plans and Milestones

Results without follow-through are the failure mode this platform exists to prevent, so every published cycle feeds **action plans** owned by line managers. A `UnitManager` creates a plan in `DRAFT` status with the `cycle_id` and `unit_id` it belongs to, a `title`, the `focus_dimension` it targets (one of the six engagement dimensions), and a `due_at` deadline that must fall strictly after the cycle's `closes_at`, per §2.5. Plan creation, and every subsequent plan act — submission, revision, start, abandonment, and adding or resolving milestones — requires the caller's `X-User-ID` to equal the `manager_user_id` of the plan's unit; any other manager is rejected with `ERR_PLAN_OWNERSHIP` (HTTP 403).

Milestones give the plan substance. The manager adds action items, each carrying a `description`, the `owner_user_id` of the accountable owner, and a `target_at` date that must not fall after the plan's `due_at` (violations are `ERR_WINDOW_VIOLATION`). New items start in `OPEN` status. Adding an item recomputes the plan's `progress_pct` and increments the plan's `version` by 1.

Submission moves the plan `DRAFT → SUBMITTED`. Three conditions guard it: the plan has at least one action item still `OPEN`; the plan's unit snapshot for the cycle is not numerically suppressed — a manager may only commit to a plan after seeing their own scores; and the caller is the unit's manager. Submission is the second OCC-guarded write of §2.12: the request must carry `expected_plan_version`, and a mismatch with the plan's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful submission stamps `submitted_at` and increments the plan's `version` by 1.

Review belongs to the `PeopleAnalyst`. Approval moves `SUBMITTED → APPROVED` and requires the cycle to be in `REPORTED` status. Rejection moves `SUBMITTED → REJECTED` and requires a non-empty `rejection_reason`, which is recorded on the plan. Both increment the plan's `version` by 1. A rejected plan is returned to the manager, who revises it — moving `REJECTED → DRAFT`, clearing `rejection_reason` back to null, and incrementing `version` — for another round. An approved plan is started by its manager, moving `APPROVED → IN_PROGRESS` with the usual version increment.

Execution resolves milestones one at a time. Marking an item done — moving it `OPEN → DONE` — requires the parent plan to be `IN_PROGRESS`, and may be performed either by the item's accountable owner (the caller's `X-User-ID` equals the item's `owner_user_id`) or by the unit's manager. Dropping an item — `OPEN → DROPPED` — likewise requires the plan to be `IN_PROGRESS`, but is the manager's act alone; the accountable owner may not drop their own milestone. Both acts recompute the plan's `progress_pct` and increment the item's `version` by 1. Progress is the count of items in `DONE`, divided by the count of all of the plan's items regardless of status, multiplied by 100 and rounded down to a whole percent; dropped items stay in the denominator, so abandoning work never inflates progress, and a plan with no items at all reports 0. When the last `OPEN` item resolves — every item now `DONE` or `DROPPED` with at least one `DONE` — the plan completes itself, moving `IN_PROGRESS → COMPLETED`, recomputing `progress_pct` to 100, and incrementing the plan's `version` by 1.

A plan whose deadline has passed may be abandoned by its manager once the logical clock is strictly after `due_at`. Abandonment is permitted from either `IN_PROGRESS` or `DRAFT`. Abandoning an `IN_PROGRESS` plan flips every remaining `OPEN` item to `DROPPED`; abandoning a `DRAFT` plan simply terminates it. Both paths land in `ABANDONED` and increment the plan's `version` by 1. Only when every plan of a cycle sits in `COMPLETED` or `ABANDONED` may the cycle be archived, per §3.5.

### 3.8. Outcome Linkage and the Attrition Risk Index

The program closes the loop by recording what actually happened to employees after a census. A `PeopleAnalyst` records an **outcome linkage** against an individual employee and a cycle, supplying the `cycle_id`, an `outcome_kind` of `ATTRITION` or `PERFORMANCE`, and an `outcome_value` — for attrition one of `VOLUNTARY`, `INVOLUNTARY`, or `NONE`, and for performance one of `BELOW`, `MEETS`, or `EXCEEDS`. The server stamps `recorded_at` at write time. Linkage rows are listed per employee or filtered across employees by cycle, employee, or outcome kind.

Each attrition linkage refreshes the cycle's `attrition_risk`, which exists in two variants. The provisional variant is computed at the `CLOSED → SCORING` transition, before any outcome linkage rows exist: it uses a prior base rate of 0.08 as a forward-looking estimate. The final variant is computed once attrition linkage rows exist for the cycle and supersedes the provisional value: the base rate is the observed ratio of attrition linkage rows whose `outcome_value` is `VOLUNTARY` or `INVOLUNTARY` to the cycle's count of `SUBMITTED` invitations, and the risk is null when that denominator is zero. Either variant then applies the engagement modifier identically: when the snapshot's `overall_score` is below the low-engagement floor of 60.00, the base rate is multiplied by the sum of 1 and the risk coefficient 1.75; otherwise it is multiplied by 1 alone. The result is rounded half-up to 4 decimal places. `attrition_risk` remains null on the cycle until scoring begins.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created` — this includes survey submissions, which create the employee's response record. Operations that modify an existing resource or drive a state transition return `200 OK`. The table below summarizes the HTTP contract only; request fields, preconditions, and side effects are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/engagement/item-banks` | Create an item bank in `DRAFT` | HRAdmin |
| GET | `/engagement/item-banks` | List item banks | HRAdmin, PeopleAnalyst |
| GET | `/engagement/item-banks/{id}` | Get one item bank | HRAdmin, PeopleAnalyst |
| POST | `/engagement/item-banks/{id}/items` | Add a survey item to a bank | HRAdmin |
| GET | `/engagement/item-banks/{id}/items` | List the items of a bank | HRAdmin, PeopleAnalyst |
| POST | `/engagement/item-banks/{id}/activate` | Activate a bank (requires at least 3 `ACTIVE` items) | HRAdmin |
| POST | `/engagement/item-banks/{id}/retire` | Retire a bank and cascade-retire its items | HRAdmin |
| POST | `/engagement/org-units` | Create an organizational unit | HRAdmin |
| GET | `/engagement/org-units` | List organizational units | HRAdmin, PeopleAnalyst, UnitManager |
| GET | `/engagement/org-units/{id}` | Get one organizational unit | HRAdmin, PeopleAnalyst, UnitManager |
| PATCH | `/engagement/org-units/{id}` | Update a unit's thresholds or parent | HRAdmin |
| POST | `/engagement/employees` | Create an employee roster row | HRAdmin |
| GET | `/engagement/employees` | List employees, filterable by unit | HRAdmin, PeopleAnalyst |
| GET | `/engagement/employees/{id}` | Get one employee | HRAdmin, PeopleAnalyst |
| POST | `/engagement/employees/{id}/terminate` | Mark an employee `TERMINATED` with exit timestamp | HRAdmin |
| POST | `/engagement/survey-cycles` | Create a survey cycle in `DRAFT` | HRAdmin |
| GET | `/engagement/survey-cycles` | List survey cycles | HRAdmin, PeopleAnalyst, UnitManager, Executive |
| GET | `/engagement/survey-cycles/{id}` | Get one cycle, including derived counters | HRAdmin, PeopleAnalyst, UnitManager, Executive |
| POST | `/engagement/survey-cycles/{id}/items` | Pin an item into the cycle | HRAdmin |
| GET | `/engagement/survey-cycles/{id}/items` | List the cycle's pinned items | HRAdmin, PeopleAnalyst |
| GET | `/engagement/cycle-items` | Filtered list of cycle items across cycles | HRAdmin, PeopleAnalyst |
| GET | `/engagement/cycle-items/{id}` | Get one cycle item | HRAdmin, PeopleAnalyst |
| POST | `/engagement/survey-cycles/{id}/configure` | Move `DRAFT → CONFIGURED` (OCC-guarded) | HRAdmin |
| POST | `/engagement/survey-cycles/{id}/open` | Move `CONFIGURED → OPEN`; runs the eligibility sweep | HRAdmin |
| POST | `/engagement/survey-cycles/{id}/close` | Move `OPEN → CLOSED`; expires open invitations | HRAdmin |
| POST | `/engagement/survey-cycles/{id}/score` | Move `CLOSED → SCORING`; generates report snapshots | PeopleAnalyst |
| POST | `/engagement/survey-cycles/{id}/publish` | Move `SCORING → REPORTED`; snapshots become manager-visible | HRAdmin |
| POST | `/engagement/survey-cycles/{id}/archive` | Move `REPORTED → ARCHIVED`; requires all plans terminal | HRAdmin |
| POST | `/engagement/survey-cycles/{id}/remind` | Bulk reminder sweep over unanswered invitations of an `OPEN` cycle | PeopleAnalyst |
| GET | `/engagement/survey-invites` | List invitations, filterable by cycle, employee, status, unit-at-invite | HRAdmin, PeopleAnalyst |
| GET | `/engagement/survey-invites/{id}` | Get one invitation; employees may read only their own | HRAdmin, PeopleAnalyst, EmployeeRole |
| POST | `/engagement/survey-invites/{id}/submit` | Submit a complete response (every item answered) | EmployeeRole |
| POST | `/engagement/survey-invites/{id}/submit-partial` | Submit a partial response (at least one item answered) | EmployeeRole |
| GET | `/engagement/survey-invites/{id}/response` | Read the response row for an invitation (array of 0 or 1) | HRAdmin, PeopleAnalyst, EmployeeRole |
| GET | `/engagement/survey-invites/{id}/reminders` | List reminder events for an invitation | HRAdmin, PeopleAnalyst |
| GET | `/engagement/report-snapshots` | List snapshots; managers restricted to their own subtree | HRAdmin, PeopleAnalyst, UnitManager, Executive |
| GET | `/engagement/report-snapshots/{id}` | Get one snapshot; confidentiality-gated | HRAdmin, PeopleAnalyst, UnitManager, Executive |
| POST | `/engagement/report-snapshots/{id}/recompute` | Re-run suppression and scoring on a snapshot; bumps its generation | PeopleAnalyst |
| GET | `/engagement/report-snapshots/{id}/verbatims` | List verbatim comments; only when not verbatim-suppressed | HRAdmin, PeopleAnalyst, UnitManager |
| POST | `/engagement/benchmark-sets` | Register a benchmark distribution | PeopleAnalyst |
| POST | `/engagement/benchmark-sets/{id}/retire` | Retire a benchmark set, excluding it from percentile computation | PeopleAnalyst |
| GET | `/engagement/benchmark-sets` | List benchmark sets | HRAdmin, PeopleAnalyst, Executive |
| POST | `/engagement/action-plans` | Create an action plan in `DRAFT` for a unit and cycle | UnitManager |
| GET | `/engagement/action-plans` | List plans; managers see their own unit only | HRAdmin, PeopleAnalyst, UnitManager, Executive |
| GET | `/engagement/action-plans/{id}` | Get one plan | HRAdmin, PeopleAnalyst, UnitManager, Executive |
| POST | `/engagement/action-plans/{id}/items` | Add a milestone item to a plan | UnitManager |
| GET | `/engagement/action-plans/{id}/items` | List a plan's milestone items | HRAdmin, PeopleAnalyst, UnitManager, Executive |
| POST | `/engagement/action-plans/{id}/submit` | Move `DRAFT → SUBMITTED` (OCC-guarded) | UnitManager |
| POST | `/engagement/action-plans/{id}/approve` | Move `SUBMITTED → APPROVED` | PeopleAnalyst |
| POST | `/engagement/action-plans/{id}/reject` | Move `SUBMITTED → REJECTED` with a reason | PeopleAnalyst |
| POST | `/engagement/action-plans/{id}/revise` | Move `REJECTED → DRAFT` | UnitManager |
| POST | `/engagement/action-plans/{id}/start` | Move `APPROVED → IN_PROGRESS` | UnitManager |
| POST | `/engagement/action-plans/{id}/abandon` | Move `DRAFT` or `IN_PROGRESS → ABANDONED` after the deadline | UnitManager |
| POST | `/engagement/action-items/{id}/complete` | Move an item `OPEN → DONE`; may auto-complete the parent plan | UnitManager |
| POST | `/engagement/action-items/{id}/drop` | Move an item `OPEN → DROPPED`; denominator kept in progress | UnitManager |
| POST | `/engagement/employees/{id}/outcome-linkages` | Record an attrition or performance outcome for an employee against a cycle | PeopleAnalyst |
| GET | `/engagement/employees/{id}/outcome-linkages` | List an employee's outcome linkages | HRAdmin, PeopleAnalyst |
| GET | `/engagement/outcome-linkages` | Filtered list of outcome linkages across employees | HRAdmin, PeopleAnalyst |
| GET | `/engagement/outcome-linkages/{id}` | Get one outcome linkage row | HRAdmin, PeopleAnalyst |
| POST | `/engagement/_clock/set_current_utc` | Set the logical clock (startup default 2026-08-01T00:00:00Z) | HRAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 where the guarded workflow is described.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CONFIDENTIALITY` | 403 |
| `ERR_DUTY_SEGREGATION` | 403 |
| `ERR_DUPLICATE` | 409 |
| `ERR_WINDOW_VIOLATION` | 422 |
| `ERR_UNIT_CYCLE` | 422 |
| `ERR_THRESHOLD_INVERSION` | 422 |
| `ERR_CYCLE_ALREADY_OPEN` | 409 |
| `ERR_INSUFFICIENT_ITEMS` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
| `ERR_ANSWERS_INCOMPLETE` | 422 |
| `ERR_INVITE_OWNERSHIP` | 403 |
| `ERR_PLAN_OWNERSHIP` | 403 |
| `ERR_SNAPSHOT_NOT_PUBLISHED` | 409 |
| `ERR_BENCHMARK_TOO_SMALL` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
