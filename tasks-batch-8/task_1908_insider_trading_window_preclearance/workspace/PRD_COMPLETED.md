# Insider Trading Compliance API — Product Requirements Document

## 1. Introduction

A public company's legal department carries a standing regulatory exposure: the people who know the most about the business — its Section 16 officers, directors, employees, and consultants — are precisely the people whose personal securities trading is most likely to collide with insider-trading law. Counsel cannot rely on goodwill alone. The department must know, at any moment, which tickers are under a quarterly earnings blackout, which are locked down because a confidential deal is in flight, which employees hold a live preclearance approval, which trades actually executed against those approvals, and which individuals are under a compliance hold because an investigation is open against them. Today these facts live in spreadsheets and inboxes; the cost of a missed blackout or an unmatched confirmation is measured in enforcement risk.

This document specifies the Insider Trading Compliance API, the system of record the legal department will operate to close that gap. The API maintains the blackout calendar — both the recurring quarterly earnings windows and event-driven windows sourced from deal intake — together with the restricted securities list. It runs the preclearance workflow from insider submission through officer decision, with approvals that carry a 48-hour validity horizon and can be voided retroactively when new blackout information emerges. A hardship exception path lets a committee grant blackout relief by quorum vote. Broker trade confirmations are ingested and matched against approvals and Rule 10b5-1 trading plans; anything that matches neither is flagged and automatically escalated into a violation case, which the department investigates, substantiates, and sanctions according to a uniform severity scoring model. Policy acknowledgments and annual training attestations gate an individual's eligibility to trade at all. Because every temporal judgment in this domain — window activation, approval expiry, cooling-off release, suspension reinstatement — must be reproducible and auditable, the entire system evaluates time against a single server-side logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and operating principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request with a missing header, a malformed header, or an unrecognized role value is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose declared role is not permitted on the target endpoint — including an `Insider` attempting to act on a resource owned by another covered person — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles:

- `Insider` — a covered person (employee, officer, director, or consultant) who submits preclearance requests, hardship exception requests, and 10b5-1 plans, and who completes their own attestations. When `X-User-Role` is `Insider`, `X-User-ID` is the `id` of the acting `CoveredPerson`; ownership checks on any resource that references a covered person compare the resource's foreign-key field (for example `covered_person_id`) to `X-User-ID`. List endpoints are not ownership-scoped: an `Insider` list call returns every record; ownership is enforced only on single-resource reads and on mutations.
- `ComplianceOfficer` — a legal department compliance officer who reviews preclearance, maintains the restricted list and the blackout calendar, runs deal intake, ingests trade confirmations, investigates violations, and runs the compliance sweep. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise the `id` of the officer's own `CoveredPerson` record — officers are themselves covered persons — and segregation-of-duties checks compare it against the owner of the request, plan, or exception being decided.
- `CommitteeMember` — a member of the exception committee who votes on hardship exception requests. When `X-User-Role` is `CommitteeMember`, `X-User-ID` is the `id` of the member's `CoveredPerson` record; it is recorded on the exception request's voter roll when a vote is cast.
- `LegalAdmin` — an operational administrator who onboards covered persons, assigns attestations, and drives the logical clock. When `X-User-Role` is `LegalAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Across all four roles the server never resolves `X-User-ID` against the data store: the header value is compared by string equality only, and a value matching no persisted record is not by itself an authentication or existence error.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.4 — never wall-clock time.
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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items are skipped and defaults to 0. Out-of-range values are clamped rather than rejected — a `limit` below 1 is read as 1 and above 100 as 100, a negative `offset` as 0 — while a non-integer `limit` or `offset` is malformed and rejected with `ERR_INVALID_REQUEST` (400). Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. The filters named in §4 are exact-match equality on the named field; a filter value that matches nothing — including one outside the field's declared enum — yields an empty page and is never an error.

### 2.4. The Logical Clock and Half-Open Time

Every temporal judgment the system makes — activating a blackout window, expiring an approval, releasing a plan from cooling-off, flipping an attestation overdue, reinstating a suspended person — reads a single server-side **logical clock**. The server never falls back to wall-clock time. Before any client sets it, the logical clock stands at exactly `2026-08-01T00:00:00Z`. A `LegalAdmin`-only test-driving capability sets the clock to a supplied `to_iso8601` instant and echoes that supplied string verbatim as the response's `current_utc`. All timestamp comparisons in this document are made at second precision against this clock. Datetime inputs are read liberally as ISO 8601: a bare date is read as midnight UTC, a `Z` suffix or numeric offset is normalized to UTC, and a naive value is read as UTC.

Blackout windows are always half-open intervals: a window covers every instant from its `start_at` up to but not including its `end_at`. Containment, overlap, and adjacency rules throughout this document are stated in those terms, and the distinction matters — an instant exactly equal to `end_at` is outside the window, while one exactly equal to `start_at` is inside it.

### 2.5. Common Resource Properties

Every resource in the system carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification.
- `version` — an integer starting at 1 on creation and incrementing by one on every mutation, including mutations the server applies automatically as part of a cascade. A deal activation increments the deal's `version`; a committee vote increments the exception request's `version`; an interval merge increments the surviving window's `version`; completing an attestation increments the covered person's `version` as their currency flags are recomputed.

### 2.6. Share Quantities, Money, and Rounding Discipline

Share quantities on requests, plans, and confirmations must be greater than zero, and inputs with up to four decimal places are accepted — a quantity carrying more is a malformed body. Execution `price` is expressed with at most two decimal places — more is likewise malformed — and carries no positivity rule. Whenever the system derives a monetary value — above all a confirmation's `trade_value` — the result is rounded half up to exactly two decimal places. Accumulated share totals on a preclearance request (`matched_quantity`, `remaining_quantity`) are likewise held at two decimal places, rounded half up, with the rounding applied to each confirmation line before accumulation; §3.7 pins that order. Severity scores and vote counts are integers. The attestation currency window is evaluated at second precision like every other timestamp comparison: a completion counts exactly when its `completed_at` falls in the closed interval from `now` minus 365 days through `now`.

### 2.7. Optimistic Concurrency Control

Three write operations guard against stale reads with an explicit expected-version field, and no other endpoint takes a version field:

- A request to `POST /preclearance-requests/{id}/decision` must carry `expected_preclearance_version` holding the `version` of the preclearance request the client last observed. If the request's version has since advanced — a review transition or another recorded mutation moved it past the observed value — the decision is rejected with `ERR_STALE_VERSION` (HTTP 412), and the deciding officer must re-read the request and decide against its current version.
- A request to `POST /tenb5-plans` must carry `expected_covered_person_version` holding the `version` of the plan owner's `CoveredPerson` record the client last observed. Creating a plan supersedes any existing draft-stage plan for the same person and ticker and increments the person's `version`, so a creation carrying a previously observed version is stale and is rejected with `ERR_STALE_VERSION` (HTTP 412).
- A request to `POST /blackout-windows/{id}/extend` must carry `expected_blackout_window_version` holding the `version` of the window the client last observed. An earlier extension already moved the window's end and incremented its version, so an extension carrying the previously observed version is stale — even though the window remains extendable — and is rejected with `ERR_STALE_VERSION` (HTTP 412).

In each case the version check is evaluated together with the operation's state checks and strictly before any side effect is applied.

### 2.8. Segregation of Duties

No one may adjudicate their own affairs. On the three decision surfaces of the system — a compliance officer deciding a preclearance request, a compliance officer deciding a 10b5-1 plan, and a committee member voting on a hardship exception — the acting user's `CoveredPerson` id must differ from the `covered_person_id` of the resource's owner. A violation of this rule is rejected with `ERR_SELF_ACTION_FORBIDDEN` (HTTP 403). This applies even where the actor's role would otherwise entitle them to the operation: an officer who submitted a request as an insider cannot then approve it wearing an officer's hat, and a committee member cannot vote on their own hardship request.

### 2.9. Validation Order and Error Precedence

When several checks could fail on the same call, the system evaluates them in a fixed order and reports the first failure. The precedence ladder is:

1. **Authentication** — missing, malformed, or unrecognized headers yield `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — a role not permitted on the endpoint, or an `Insider` acting on another person's resource, yields `ERR_UNAUTHORIZED` (403). The ownership half of this check runs against the identifier already in hand: on creation payloads (`covered_person_id` must equal `X-User-ID`) and on `GET /covered-persons/{id}`, where the path id is itself the owner key, it fires before existence, so an unknown id there still yields `ERR_UNAUTHORIZED`; on every other endpoint the path id is resolved first, so an unknown id yields `ERR_NOT_FOUND` and ownership is checked only against a resource that exists.
3. **Existence** — path-template resource ids are validated left to right, then foreign keys referenced in the request body (`covered_person_id`, `exception_id`, `trade_confirmation_id`) are validated; a missing resource yields `ERR_NOT_FOUND` (404). Security tickers are free strings and are never existence-validated against a registry.
4. **State validity** — the target resource must be in a valid from-state for the requested transition, including terminal-state lockdown, else `ERR_INVALID_STATE` (409). The optimistic-concurrency version check rides with this group and is always enforced before any side effect, even though as an error class it is listed after the business screens below; a stale version yields `ERR_STALE_VERSION` (412).
5. **Segregation of duties** — `ERR_SELF_ACTION_FORBIDDEN` (403) per §2.8.
6. **Business safety screens** — the restricted-list screen yields `ERR_SECURITY_RESTRICTED` (422); the compliance-hold screen yields `ERR_COMPLIANCE_HOLD` (422).
7. **Temporal screens** — blackout coverage yields `ERR_TRADE_IN_BLACKOUT` (422); date-range sanity yields `ERR_DATE_RANGE_INVALID` (422).
8. **Eligibility constraints** — policy acknowledgment is checked before training currency: a person whose `policy_ack_current` is false draws `ERR_POLICY_ACK_REQUIRED` (422); a person whose acknowledgment is current but whose `training_current` is false draws `ERR_TRAINING_OVERDUE` (422).
9. **Conflict and constraint checks** — duplicate committee vote (`ERR_DUPLICATE_VOTE`, 409), overlapping quarterly window (`ERR_DUPLICATE_QUARTER_WINDOW`, 409), duplicate restricted entry (`ERR_DUPLICATE_RESTRICTED_ENTRY`, 409), overlapping approval lane (`ERR_OVERLAPPING_APPROVAL`, 409), exception quantity cap (`ERR_QUANTITY_EXCEEDS_APPROVED`, 422), and duplicate open case (`ERR_CASE_ALREADY_OPEN`, 409).
10. **Body schema** — `ERR_INVALID_REQUEST` (400) covers a missing required field or malformed value such as a bad datetime or a non-positive quantity, and `ERR_INVALID_ENUM` (400) covers an enum field carrying a value outside its declared set. These two checks are syntactic: a malformed body can never reach the deeper rules, and every other check in the ladder outranks the schema checks, so a 400 of either kind is only ever observable as the sole failing check of a request. When one body fails both schema checks, `ERR_INVALID_REQUEST` is reported in preference to `ERR_INVALID_ENUM`.

### 2.10. Atomic Cascades and the Compliance Sweep

Many operations in this domain mutate more than one entity at once — a deal activation creates a restricted entry, spawns an event window, and denies pending requests in a single stroke. Every such cascade is applied atomically within the triggering request: either the whole cascade commits or the operation fails outright, and each mutated resource's `updated_at` and `version` advance per §2.5.

Deferred work is driven by a single officer-invoked capability: the **compliance sweep**. A sweep reads the current logical clock and performs its work in a pinned eight-step order:

1. Blackout windows due to activate — `SCHEDULED` windows whose `start_at` has been reached but whose `end_at` has not yet passed — move to `ACTIVE`, processed in ascending `start_at` order with ties broken by ascending `created_at`, each firing the approval-voiding cascade described in §3.4.
2. `ACTIVE` windows whose `end_at` has been reached or passed move to `LIFTED`.
3. `APPROVED` preclearance requests whose validity horizon has passed move to `EXPIRED`.
4. `SUBMITTED` exception requests past their decision window move to `EXPIRED`.
5. `APPROVED` 10b5-1 plans whose cooling-off has elapsed move to `ACTIVE`.
6. `ASSIGNED` attestations whose `due_date` has passed move to `OVERDUE`, and each affected person's training currency is recomputed.
7. `SUSPENDED` covered persons whose suspension has elapsed return to `ACTIVE`.
8. A re-match pass runs over every trade confirmation resting in `RECEIVED` when this step begins — including any confirmation returned to `RECEIVED` by an approval voided in step 1 of the same sweep — processed in ascending `trade_date` order with ties broken by ascending `created_at`, re-running the matching rules of §3.7.

Within each step, records iterate in ascending `created_at` order unless a different order is pinned above. The sweep response reports how much work it did, as counts: `windows_activated`, `windows_lifted`, `approvals_expired`, `approvals_voided`, `exceptions_expired`, `plans_activated`, `attestations_overdue`, `persons_reinstated`, and `confirmations_remanaged`.

## 3. Business Logic & Workflows

### 3.1. Covered Persons and the Eligibility to Trade

Everything in the system hangs off the **covered person**. A `LegalAdmin` onboards one by supplying a `full_name`, a work `email` that must be unique across all covered persons — a duplicate is rejected with `ERR_INVALID_REQUEST` (400), evaluated only once the body schema itself passes — a `designation` of `SECTION_16_OFFICER`, `DIRECTOR`, `EMPLOYEE`, or `CONSULTANT`, and a `department`. The designation is not decorative: it selects the cooling-off variant for 10b5-1 plans (§3.6) and adds a severity bonus when sanctions are scored (§3.8). A freshly created person starts with `status` `ACTIVE`, both currency flags false, and `version` 1.

Two computed flags summarize whether a person is currently eligible to trade at all. `policy_ack_current` is true exactly when the person has a `COMPLETED` attestation of kind `POLICY_ACK` whose `completed_at` falls within the trailing 365 days of now. `training_current` is true exactly when the person has a `COMPLETED` attestation of kind `ANNUAL_TRAINING` within the same trailing 365-day window **and** no `OVERDUE` `ANNUAL_TRAINING` attestation exists for them — an overdue training assignment poisons training currency even if an older completion would otherwise still count. A third computed flag, `compliance_hold`, is true exactly when the person has a violation case in any of `OPENED`, `UNDER_INVESTIGATION`, `ESCALATED`, `SUBSTANTIATED`, or `SANCTION_RECORDED`.

Attestations are assigned by a `LegalAdmin`, who supplies the `covered_person_id` of the assignee, a `kind` (`POLICY_ACK` or `ANNUAL_TRAINING`), the `period_year`, and a `due_date`; the attestation begins `ASSIGNED`. The assignee — acting as an `Insider`, so `X-User-ID` must equal the attestation's `covered_person_id` — completes it, which stamps `completed_at`, moves the record to `COMPLETED`, recomputes the person's currency flags, and increments the person's `version`. Completion is accepted from `ASSIGNED` and also from `OVERDUE`: late completion is allowed and restores currency. The overdue flip itself is deferred work — when the sweep finds an `ASSIGNED` attestation whose `due_date` is earlier than now, it moves the attestation to `OVERDUE` and recomputes the person's `training_current`.

A person may also lose standing through discipline. When a sanction of `SUSPENSION_30D` or `SUSPENSION_90D` is recorded (§3.8), the person's `status` moves from `ACTIVE` to `SUSPENDED` and `suspended_until` is set to thirty or ninety days from that moment, respectively. When the sweep finds a `SUSPENDED` person whose `suspended_until` has been reached or passed, it reinstates them to `ACTIVE` and clears `suspended_until` to null.

These flags gate the two insider-initiated creation workflows. Submitting a preclearance request and creating a 10b5-1 plan both require the subject to be free of a compliance hold (`ERR_COMPLIANCE_HOLD`, 422), to hold a current policy acknowledgment (`ERR_POLICY_ACK_REQUIRED`, 422), and to hold current training (`ERR_TRAINING_OVERDUE`, 422) — evaluated in that order, so a person missing both currency flags always sees the policy-acknowledgment error first.

### 3.2. The Blackout Calendar: Quarterly and Event-Driven Windows

The blackout calendar is the temporal backbone of the compliance regime, and it comes in two kinds. A `QUARTERLY` window marks the earnings blackout around a fiscal quarter and is created with a `fiscal_year` and a `fiscal_quarter` of `Q1`, `Q2`, `Q3`, or `Q4`; it applies to every ticker. An `EVENT_DRIVEN` window marks a deal- or event-specific blackout and carries the `security_ticker` it applies to — populated from the creation input when an officer creates it directly, or from the sourcing deal when deal intake spawns it; it applies to that ticker only. Each window records this scope in a derived `applicability_note`: literally `QUARTERLY window applies to all tickers` on a quarterly window, and `EVENT_DRIVEN window applies to <ticker> only` on an event window. A compliance officer creates a window by supplying `kind`, `start_at`, and `end_at`, plus the kind-specific fields; omitting the fiscal fields on a quarterly window or the ticker on an event window is a malformed body (`ERR_INVALID_REQUEST`), and an `end_at` that is not strictly later than `start_at` is rejected with `ERR_DATE_RANGE_INVALID` (422). On the date-range check fires before any kind-specific conflict check. Fields inapplicable to the window's kind — fiscal fields on an `EVENT_DRIVEN` window, `security_ticker` on a `QUARTERLY` window — are ignored when supplied, never rejected.

Quarterly windows are exclusive. If the half-open interval of a new `QUARTERLY` window overlaps the half-open interval of an existing `SCHEDULED` or `ACTIVE` `QUARTERLY` window, creation is rejected with `ERR_DUPLICATE_QUARTER_WINDOW` (409). Adjacency is not overlap: a new quarterly window whose `start_at` equals an existing window's `end_at` is accepted.

Event-driven windows never collide — they **merge**. When a new `EVENT_DRIVEN` window for a ticker overlaps or touches an existing `SCHEDULED` or `ACTIVE` `EVENT_DRIVEN` window on the same ticker — where touching means the candidate's `start_at` equals the survivor's `end_at` or vice versa — the candidate is absorbed. The surviving window's `start_at` becomes the earlier of the two starts, its `end_at` becomes the later of the two ends, and its `version` increments. The candidate record is still created, but is immediately set to `MERGED` with its `merged_into_id` pointing at the survivor; the candidate keeps `version` 1, the merge riding on its creation, while the surviving window and each other absorbed window each increment their `version` once. If several existing windows touch the candidate, they are absorbed into the one with the earliest `start_at` (ties broken by ascending `created_at`), and the other survivors themselves become `MERGED` into it. When no existing window overlaps or touches the candidate, the candidate simply remains `SCHEDULED`. `QUARTERLY` windows never merge, and the merge rule applies identically to officer-created windows and to windows spawned by deal activation.

Once created, a window's life is driven by the clock. The sweep moves a `SCHEDULED` window to `ACTIVE` once now is at or past `start_at` while still before `end_at`, and moves an `ACTIVE` window to `LIFTED` once now is at or past `end_at`. Activation is the dangerous moment: it is what voids standing approvals, as §3.4 details. An officer may cancel a window, but only from `SCHEDULED` — the record moves to `CANCELLED`, and attempting to cancel from any other state is `ERR_INVALID_STATE` (409). An officer may also extend a window, whether `SCHEDULED` or `ACTIVE`, by supplying a `new_end_at` strictly later than the current `end_at` (otherwise `ERR_DATE_RANGE_INVALID`) together with the OCC guard `expected_blackout_window_version` (§2.7); a successful extension moves `end_at` to `new_end_at` and increments the window's `version` — an extension never re-runs the merge rule. Deal-sourced windows additionally carry a `deal_id` back-reference, which is what lets deal closure find and retire them (§3.3). `LIFTED`, `CANCELLED`, and `MERGED` are terminal.

### 3.3. Deal Intake and the Restricted List

Confidential corporate actions enter the system as **deals**. A `ComplianceOfficer` performs deal intake by supplying a confidential `codename`, a `deal_type` of `MERGER`, `ACQUISITION`, `DIVESTITURE`, `FINANCING`, or `RESTRUCTURING`, the listed `security_ticker` the deal affects, and optionally an `event_blackout_start` with its `event_blackout_end`. If the end is supplied without the start, intake is rejected with `ERR_DATE_RANGE_INVALID`; when both are present, the end must be strictly later than the start under the same rule. A new deal begins in `INTAKE`.

Activation is the pivotal event in a deal's life, and it fires a three-part atomic cascade. Moving a deal from `INTAKE` to `ACTIVE` stamps `activated_at`, increments the deal's `version`, and then, in the same transaction: first, a `RestrictedListEntry` is always created for the deal's ticker with `source` `DEAL_INTAKE`, a `deal_id` back-reference, and `status` `ACTIVE` — this happens even when a `MANUAL` entry for the same ticker is already active, because multiple active entries per ticker are permitted across different sources; second, if the deal carries an `event_blackout_start`, an `EVENT_DRIVEN` blackout window is created over that interval for the deal's ticker with the same `deal_id` back-reference, subject to the merge rule of §3.2; third, every preclearance request on that ticker sitting in `SUBMITTED` or `UNDER_REVIEW` is automatically denied, with `denial_reason` set to `RESTRICTED_LIST`.

Closing a deal unwinds what activation built, with the unwind shape depending on the `outcome` the officer supplies. Closing as `COMPLETED` moves the deal from `ACTIVE` to `CLOSED`: deal-sourced restricted entries that are still `ACTIVE` are removed with `removed_reason` `DEAL_CLOSED`, deal-sourced windows that are `ACTIVE` are lifted to `LIFTED`, and deal-sourced windows still `SCHEDULED` are cancelled to `CANCELLED`. Closing as `ABANDONED` moves the deal to `ABANDONED`: the same restricted-entry removal applies, but every deal-sourced window in either `SCHEDULED` or `ACTIVE` is cancelled — an abandoned deal lifts nothing. Both paths stamp `closed_at` and increment the deal's `version`, and both `CLOSED` and `ABANDONED` are terminal.

The restricted list can also be maintained by hand. An officer adds a ticker with a `security_ticker` and an optional free-text `note`, producing an `ACTIVE` entry whose `source` is `MANUAL`. Manual creation is the one place a duplicate is blocked: if any entry for that ticker is already `ACTIVE` — regardless of its source — creation is rejected with `ERR_DUPLICATE_RESTRICTED_ENTRY` (409). Manual creation fires the same auto-denial cascade as deal activation: pending preclearance requests on the ticker in `SUBMITTED` or `UNDER_REVIEW` are denied with `denial_reason` `RESTRICTED_LIST`. An officer removes an entry, moving it from `ACTIVE` to the terminal `REMOVED` with `removed_reason` `MANUAL`; removal from any other state is `ERR_INVALID_STATE`.

While any `ACTIVE` entry exists for a ticker, the list has teeth in two places: submitting a new preclearance request on that ticker is rejected with `ERR_SECURITY_RESTRICTED` (422), and approving a request already under review on that ticker is rejected with the same code.

### 3.4. Preclearance: Submission, Review, and the Life of an Approval

An insider who wants to trade submits a **preclearance request** naming themselves — `covered_person_id` must equal `X-User-ID`, otherwise `ERR_UNAUTHORIZED` — along with the `security_ticker`, the `trade_side` (`BUY` or `SELL`), the `quantity` of shares, the intended `proposed_trade_date`, and optionally an `exception_id` citing a hardship exception (§3.5). The request is born `SUBMITTED`, with `matched_quantity` 0 and `remaining_quantity` null until an approval initializes it.

Submission runs a gauntlet of checks, evaluated in a fixed order so that earlier failures are never masked by later ones: the restricted-list screen first (`ERR_SECURITY_RESTRICTED`), then the compliance-hold screen (`ERR_COMPLIANCE_HOLD`), then the blackout screen (`ERR_TRADE_IN_BLACKOUT`), then policy acknowledgment (`ERR_POLICY_ACK_REQUIRED`), then training currency (`ERR_TRAINING_OVERDUE`), then the overlapping-approval lane (`ERR_OVERLAPPING_APPROVAL`, 409), and finally — only when `exception_id` is present — the exception quantity cap (`ERR_QUANTITY_EXCEEDS_APPROVED`, 422).

The blackout screen applies what this document calls the **provisional validity** verdict. A submission is blocked when a `SCHEDULED` or `ACTIVE` blackout window that applies to the request — every `QUARTERLY` window applies; an `EVENT_DRIVEN` window applies when its ticker matches the request's `security_ticker` — has a half-open interval containing the `proposed_trade_date`. The block is lifted when the request cites, via `exception_id`, an exception request that is `APPROVED`, covers the same ticker, and covers a `quantity` at least as large as the request's: the exception bypass. The same screen, same bypass, and same error code apply when an officer later approves the request.

The overlapping-approval lane prevents stacked live approvals: if the same person and ticker already hold an `APPROVED` request whose closed approval window — the interval from its `decided_at` through its `approval_valid_until`, both ends inclusive — contains the new `proposed_trade_date`, submission is rejected with `ERR_OVERLAPPING_APPROVAL`. When an exception is cited, the request's `quantity` must not exceed the exception's covered `quantity`, or submission fails with `ERR_QUANTITY_EXCEEDS_APPROVED`.

Review is a two-step officer workflow. An officer first moves a `SUBMITTED` request to `UNDER_REVIEW`, incrementing its `version`. The decision then lands on an `UNDER_REVIEW` request via a payload carrying an `outcome` of `APPROVE` or `DENY`, an optional `denial_reason`, and the OCC guard `expected_preclearance_version`. Decision-time checks run in order: the request must be `UNDER_REVIEW` (`ERR_INVALID_STATE`), the version must match (`ERR_STALE_VERSION`, riding with the state group per §2.9 and enforced before any side effect), segregation of duties forbids deciding one's own request (`ERR_SELF_ACTION_FORBIDDEN`), and — for an `APPROVE` outcome only — the restricted-list screen applies (`ERR_SECURITY_RESTRICTED`) and the provisional blackout screen applies (`ERR_TRADE_IN_BLACKOUT`); a `DENY` is never blocked by either screen. An `APPROVE` outcome stamps `decided_at` and `decided_by`, computes `approval_valid_until` as exactly 48 hours after the decision instant, initializes `remaining_quantity` to the full `quantity`, and increments `version`. A `DENY` outcome stamps the same decision fields, records `denial_reason` as `OFFICER_DISCRETION` — a `denial_reason` supplied in the payload is ignored, though when present it must be `RESTRICTED_LIST` or `OFFICER_DISCRETION`, else `ERR_INVALID_ENUM` — and terminates the request. `DENIED` is terminal in either flavor — officer discretion or the restricted-list cascade of §3.3, the latter stamping no decision fields: `decided_at` and `decided_by` stay null. The requesting insider may withdraw their own request from `SUBMITTED` or `UNDER_REVIEW`, moving it to the terminal `WITHDRAWN`.

An `APPROVED` request then lives out one of three exits. It may be **consumed**: as §3.7 describes, matching confirmations draw down `remaining_quantity`, and when the remainder reaches zero the request closes itself — `CLOSED` is terminal. It may **expire**: the sweep moves an `APPROVED` request to `EXPIRED` once now is strictly later than `approval_valid_until`; confirmations already matched stay matched, and whatever `remaining_quantity` was left is forfeited — the field is set to 0 while `matched_quantity` persists unchanged. Or it may be **voided** — the final validity verdict. Approval screens the calendar only as known at decision time, and a window created after `decided_at` cannot retroactively block the decision; but when such a later-created window later activates, the sweep's activation cascade re-evaluates. Every `APPROVED` request whose `proposed_trade_date` falls inside the activating window's half-open interval, and to which that window applies, moves to `VOIDED` — unless the request carries a valid exception bypass, which protects it from voiding exactly as it protected it from the decision-time screen. Voiding unwinds consumption: each confirmation matched to the request returns to `RECEIVED` with its `match_preclearance_id` cleared, while the request's `matched_quantity` resets to zero and its `remaining_quantity` is restored to the full `quantity`. Identical trade data can therefore produce different outcomes under the provisional and final verdicts — an approval valid when granted is void the moment a younger window activates over its trade date.

### 3.5. Hardship Exceptions and the Committee Vote

When a blackout would work a genuine hardship — a tax deadline, a medical emergency — an insider may petition the exception committee. The insider submits an **exception request** with their own `covered_person_id`, the `security_ticker` the exception covers, the maximum `quantity` of shares it covers, and a free-text `hardship_reason`. The request is born `SUBMITTED`, and the system immediately computes `decision_window_end` as five days after creation: the committee's clock is already ticking.

Committee members vote with a payload carrying a `vote` of `APPROVE` or `REJECT`. Each vote appends the member's `CoveredPerson` id to the request's `voter_ids`, recomputes `votes_for` and `votes_against`, and increments the request's `version`. Three guards apply, in order: voting on a request no longer `SUBMITTED` is `ERR_INVALID_STATE`; a member voting on their own hardship request violates segregation of duties (`ERR_SELF_ACTION_FORBIDDEN`); and a member whose id already appears in `voter_ids` is rejected with `ERR_DUPLICATE_VOTE` (409).

The committee decides by quorum. After each vote is tallied, if `votes_for` has reached two the request is decided `APPROVED`; otherwise, if `votes_against` has reached two it is decided `DENIED` — exactly two approvals decide, and exactly two rejections decide. A request that has reached neither threshold remains `SUBMITTED`. Deciding stamps `decided_at`. If the decision window closes first — the sweep finds a still-`SUBMITTED` request whose `decision_window_end` is earlier than now — the request moves to `EXPIRED`. The petitioner may also withdraw their own request from `SUBMITTED`, moving it to `WITHDRAWN`. All four of `APPROVED`, `DENIED`, `WITHDRAWN`, and `EXPIRED` are terminal.

An `APPROVED` exception is the only instrument that beats the blackout screen. Cited through `exception_id` on a preclearance request, it bypasses the blackout check for its ticker up to its covered `quantity`, both at submission and at decision time, and it protects the resulting approval from being voided when a younger window later activates. The bypass is narrow: it confers no relief from the restricted-list screen, which applies to exception-backed requests exactly as to any other.

### 3.6. 10b5-1 Trading Plans and the Cooling-Off Period

A Rule 10b5-1 plan lets an insider pre-commit to a trading program while not in possession of inside information, then trade under it later with a good-faith defense. An insider creates a plan with their own `covered_person_id`, the `security_ticker` the plan will trade, the `total_quantity` of shares it may trade, the `first_trade_date` it authorizes, and the OCC guard `expected_covered_person_version` (§2.7). Creation is gated on the owner's standing — compliance hold first (`ERR_COMPLIANCE_HOLD`), then policy acknowledgment (`ERR_POLICY_ACK_REQUIRED`), then training currency (`ERR_TRAINING_OVERDUE`) — and on the version match (`ERR_STALE_VERSION`). The new plan begins as a `DRAFT`.

Creation **supersedes**: any existing plan of the same owner for the same ticker sitting in `DRAFT`, `SUBMITTED`, or `RETURNED` is automatically moved to `CANCELLED`, and the owner's `CoveredPerson` record increments its `version`. That increment is exactly why the OCC guard exists — a client holding the person's version from before a first creation will find a second creation rejected as stale.

The owner submits a `DRAFT` plan for review, moving it to `SUBMITTED`. An officer then decides with an `outcome` of `APPROVE` or `RETURN`; segregation of duties applies (`ERR_SELF_ACTION_FORBIDDEN`). Approval stamps `approved_at` and `approved_by` and computes the plan's `cooling_off_end` by the owner's designation variant. Under the `STANDARD` variant — owners designated `EMPLOYEE` or `CONSULTANT` — cooling-off ends thirty days after `approved_at`. Under the `EXECUTIVE` variant — owners designated `SECTION_16_OFFICER` or `DIRECTOR` — cooling-off ends at the later of two instants: ninety days after `approved_at`, or two days after the `end_at` of the `QUARTERLY` blackout window whose half-open interval contains `approved_at` — when several contain the instant, the one with the latest `end_at` — considering quarterly windows in any status other than `MERGED`; when no quarterly window contains the approval instant, the executive rule reduces to ninety days after `approved_at`. Identical approval instants therefore yield a later `cooling_off_end` for executives than for staff. A `RETURN` decision instead records the officer's `return_note` on the plan (`return_note` is optional; omitted, it is stored as null), and the owner may revise and submit again — `RETURNED` plans submit back to `SUBMITTED` in a revision loop that can repeat indefinitely.

Plans do not trade on approval. The sweep moves an `APPROVED` plan to `ACTIVE` only once now is at or past its `cooling_off_end`. From there, in-life management runs through a payload carrying a single `action` verb: `SUSPEND` moves an `ACTIVE` plan to `SUSPENDED` (officers only), `RESUME` returns a `SUSPENDED` plan to `ACTIVE` (officers only), and `TERMINATE` moves a plan in `DRAFT`, `ACTIVE`, or `SUSPENDED` to the terminal `TERMINATED` — available to the owning insider or an officer alike. Attempting an action from any other from-state, including terminating a `SUBMITTED`, `RETURNED`, or `APPROVED` plan, is `ERR_INVALID_STATE`. Every submission, decision, and action increments the plan's `version`.

### 3.7. Trade Confirmation Ingestion and Matching

Execution data arrives as **trade confirmations**. A compliance officer ingests a broker confirmation carrying the executing insider's `covered_person_id`, the `security_ticker`, the `trade_side` (`BUY` or `SELL`), the executed `quantity`, the execution `price` per share, the `trade_date`, and the broker's confirmation reference `broker_ref`. The system derives `trade_value` as the executed `quantity` multiplied by `price`, rounded half up to two decimal places; this value later feeds the sanction severity bands of §3.8. Ingestion runs the matching pass synchronously, and the response shows the confirmation's resolved status: `MATCHED_PRECLEARANCE`, `MATCHED_PLAN`, or `FLAGGED`. That resolution rides on the creation itself, so the response carries `version` 1. `RECEIVED` is the confirmation's entry state and, later, the resting state of a released match — the sweep's eighth step re-runs the matching pass over every confirmation sitting in `RECEIVED`.

The matching pass tries lanes in a fixed order. First, the preclearance lane: a qualifying request shares the confirmation's `covered_person_id`, `security_ticker`, and `trade_side`; is `APPROVED`; has an approval window containing the `trade_date` — that is, `trade_date` no earlier than the request's `decided_at` and no later than its `approval_valid_until`, both ends inclusive; and has a `remaining_quantity` at least as large as the confirmation's `quantity`. Among all qualifying requests the matcher selects the one with the earliest `decided_at`, breaking ties by ascending `created_at`. On a match, the confirmation records the request in `match_preclearance_id` and the request consumes quantity with a pinned rounding order: the applied amount is the smaller of the confirmation's `quantity` and the request's `remaining_quantity`, rounded half up to two decimal places before any accumulation; the request's `matched_quantity` then increases by the applied amount and its `remaining_quantity` decreases by the applied amount, each re-rounded half up to two decimal places. The order is load-bearing — two confirmations of 10.005 shares each accumulate a `matched_quantity` of 20.02 under this rule, where summing the raw quantities and rounding once at the end would yield 20.01. When consumption drives `remaining_quantity` to zero, the request moves from `APPROVED` to `CLOSED`.

Failing the preclearance lane, the matcher tries the plan lane: a qualifying plan shares the confirmation's `covered_person_id` and `security_ticker`, is `ACTIVE`, and has a `trade_date` no earlier than its `cooling_off_end` and no earlier than its `first_trade_date`. Among qualifying plans the matcher selects the one with the earliest `approved_at`, breaking ties by ascending `created_at`, and the confirmation records it in `match_plan_id`; the plan itself is not mutated — no quantity is drawn down and its `version` does not advance. `MATCHED_PLAN` is terminal.

Failing both lanes, the confirmation is `FLAGGED`, and the system asks why. If an `ACTIVE` blackout window applicable to the ticker covers the `trade_date`, `flagged_reason` is `BLACKOUT_TRADE`; otherwise, if an `ACTIVE` restricted-list entry matches the ticker, `flagged_reason` is `RESTRICTED_LIST`; otherwise it is `NO_PRECLEARANCE`. Flagging fires an atomic cascade: a violation case opens against the insider with `violation_type` equal to the flagged reason, `source` `AUTO_FLAG`, `status` `OPENED`, and a `trade_confirmation_id` back-reference — unless a case not yet `CLOSED` already references that confirmation, in which case no second case is opened (the confirmation is still flagged and the hold still recomputes); the `ERR_CASE_ALREADY_OPEN` (409) rejection applies only to manual case creation (§3.8) — and the insider's `compliance_hold` recomputes to true, immediately gating their new preclearance submissions and plan creations with `ERR_COMPLIANCE_HOLD`.

Two reversal paths exist. When an approval is voided (§3.4), every confirmation matched to it returns from `MATCHED_PRECLEARANCE` to `RECEIVED` with `match_preclearance_id` cleared, eligible for re-matching in that same sweep's step-8 re-match pass. And when the violation case that auto-opened from a flag is eventually closed as unfounded (§3.8), the linked confirmation moves from `FLAGGED` to the terminal `CLEARED`.

### 3.8. Violation Cases, Sanctions, and Reinstatement

Every allegation of a policy breach lives in a **violation case**, whether it arrives through the flag cascade of §3.7 or is opened by hand. An officer opening a case manually supplies the subject's `covered_person_id`, a `violation_type` of `BLACKOUT_TRADE`, `NO_PRECLEARANCE`, `RESTRICTED_LIST`, `PLAN_VIOLATION`, or `OTHER`, and optionally a `trade_confirmation_id` — existence-checked only, it need not reference one of the subject's own confirmations — and free-text `note`; the case begins `OPENED` with `source` `MANUAL`, and the subject's `compliance_hold` is recomputed on the spot. One confirmation, one open case: if a case not yet `CLOSED` already references the same `trade_confirmation_id`, creation is rejected with `ERR_CASE_ALREADY_OPEN`.

Investigation proceeds through a payload carrying a single `action` verb. `BEGIN_INVESTIGATION` moves an `OPENED` case to `UNDER_INVESTIGATION`. `ESCALATE` moves an `UNDER_INVESTIGATION` case to `ESCALATED`, and `DEESCALATE` returns an `ESCALATED` case to `UNDER_INVESTIGATION` — the escalation cycle can repeat as often as the facts demand. From either `UNDER_INVESTIGATION` or `ESCALATED`, the officer reaches a finding: `SUBSTANTIATE` moves the case to `SUBSTANTIATED`, while `UNFOUND` moves it to `UNFOUNDED`. From `SUBSTANTIATED`, `RECORD_SANCTION` moves the case to `SANCTION_RECORDED`; from there, `CLOSE` moves it to the terminal `CLOSED`. An `UNFOUNDED` case also closes via `CLOSE`. Any action attempted from an incompatible from-state is `ERR_INVALID_STATE`, and every action increments the case's `version`.

Substantiation is where the **severity score** is computed, from four components. The base points come from the `violation_type`: 40 for `BLACKOUT_TRADE`, 50 for `RESTRICTED_LIST`, 30 for `PLAN_VIOLATION`, 25 for `NO_PRECLEARANCE`, and 15 for `OTHER`. Repeat behavior adds 15 points for each of the subject's other cases — those already in `SANCTION_RECORDED` or `CLOSED` with a recorded `sanction`. Size adds a value-band bonus read off the linked confirmation's `trade_value`: 20 points when the value is at least 100,000; 10 points when it is at least 25,000 but below 100,000; nothing below 25,000, and nothing when no confirmation is linked at all. Seniority adds 10 points when the subject's `designation` is `SECTION_16_OFFICER` or `DIRECTOR`. The `severity_score` is the sum of these components, capped at 100.

Recording the sanction maps that score to a penalty: a score of 75 or more yields `TERMINATION_REFERRAL`; 50 or more, `SUSPENSION_90D`; 25 or more, `SUSPENSION_30D`; below 25, `WARNING`. The recording stamps `sanction_recorded_at`, and when the sanction is a suspension the subject's `CoveredPerson` record moves from `ACTIVE` to `SUSPENDED` with `suspended_until` set thirty or ninety days out per §3.1 — recording a suspension on an already-`SUSPENDED` person simply re-stamps `suspended_until` from the new sanction instant.

Closing disposes of the case's loose ends, and the two close paths differ. Closing a `SANCTION_RECORDED` case recomputes the subject's `compliance_hold` — it falls to false if no other open case remains. Closing an `UNFOUNDED` case does that and one thing more: the linked confirmation, if still `FLAGGED`, moves to `CLEARED`. Reinstatement after a suspension is not a case action at all — it is deferred work, handled by the sweep when the person's `suspended_until` has been reached, as §3.1 describes.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, advance its workflow, or run a system capability return `200 OK`. Request payloads, side effects, and the full state semantics of each operation are defined by the narratives of §2 and §3; this table is the index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to `to_iso8601`; the default before any call is exactly `2026-08-01T00:00:00Z` and the server never falls back to wall-clock time | LegalAdmin |
| POST | `/covered-persons` | Create a covered person | LegalAdmin |
| GET | `/covered-persons/{id}` | Get a covered person | Insider, ComplianceOfficer, CommitteeMember, LegalAdmin |
| GET | `/covered-persons` | List covered persons (paginated; filterable by `designation`, `status`) | Insider, ComplianceOfficer, CommitteeMember, LegalAdmin |
| POST | `/deals` | Deal intake | ComplianceOfficer |
| GET | `/deals/{id}` | Get a deal | ComplianceOfficer, LegalAdmin |
| POST | `/deals/{id}/activate` | Activate a deal: creates the restricted entry and optional event window, auto-denies pending preclearances on the ticker | ComplianceOfficer |
| POST | `/deals/{id}/close` | Close a deal (`outcome` `COMPLETED`) or abandon it (`outcome` `ABANDONED`); removes deal-sourced entries and retires deal-sourced windows | ComplianceOfficer |
| GET | `/deals/{id}/restricted-list-entries` | List restricted list entries sourced from a deal | ComplianceOfficer, LegalAdmin |
| POST | `/restricted-list-entries` | Manually add a ticker to the restricted list | ComplianceOfficer |
| GET | `/restricted-list-entries` | List restricted list entries (paginated; filterable by `security_ticker`, `status`) | ComplianceOfficer, LegalAdmin |
| POST | `/restricted-list-entries/{id}/remove` | Remove an entry from the restricted list | ComplianceOfficer |
| POST | `/blackout-windows` | Create a `QUARTERLY` or `EVENT_DRIVEN` blackout window; event windows merge on overlap or touch with an existing event window on the same ticker | ComplianceOfficer |
| GET | `/blackout-windows/{id}` | Get a blackout window | Insider, ComplianceOfficer, CommitteeMember, LegalAdmin |
| GET | `/blackout-windows` | List blackout windows (paginated; filterable by `kind`, `status`, `security_ticker`, `deal_id`, `merged_into_id`) | Insider, ComplianceOfficer, CommitteeMember, LegalAdmin |
| POST | `/blackout-windows/{id}/cancel` | Cancel a `SCHEDULED` window | ComplianceOfficer |
| POST | `/blackout-windows/{id}/extend` | Extend a `SCHEDULED` or `ACTIVE` window's `end_at` (OCC-guarded via `expected_blackout_window_version`) | ComplianceOfficer |
| POST | `/preclearance-requests` | Submit a preclearance request | Insider |
| GET | `/preclearance-requests/{id}` | Get a preclearance request | Insider, ComplianceOfficer, LegalAdmin |
| GET | `/preclearance-requests` | List preclearance requests (paginated; filterable by `covered_person_id`, `status`) | Insider, ComplianceOfficer, LegalAdmin |
| POST | `/preclearance-requests/{id}/review` | Move a request to `UNDER_REVIEW` | ComplianceOfficer |
| POST | `/preclearance-requests/{id}/decision` | Approve or deny an `UNDER_REVIEW` request (OCC-guarded via `expected_preclearance_version`; segregation of duties) | ComplianceOfficer |
| POST | `/preclearance-requests/{id}/withdraw` | Withdraw a `SUBMITTED` or `UNDER_REVIEW` request | Insider |
| GET | `/preclearance-requests/{id}/trade-confirmations` | List confirmations matched to a request | Insider, ComplianceOfficer, LegalAdmin |
| POST | `/exception-requests` | Submit a hardship exception request | Insider |
| GET | `/exception-requests/{id}` | Get an exception request | Insider, ComplianceOfficer, CommitteeMember, LegalAdmin |
| GET | `/exception-requests` | List exception requests (paginated; filterable by `covered_person_id`, `status`) | Insider, ComplianceOfficer, CommitteeMember, LegalAdmin |
| POST | `/exception-requests/{id}/vote` | Cast a committee vote; a quorum of two decides `APPROVED` or `DENIED` | CommitteeMember |
| POST | `/exception-requests/{id}/withdraw` | Withdraw a `SUBMITTED` exception request | Insider |
| GET | `/exception-requests/{id}/preclearance-requests` | List preclearance requests citing this exception | Insider, ComplianceOfficer, CommitteeMember, LegalAdmin |
| POST | `/tenb5-plans` | Create a 10b5-1 plan (OCC-guarded via `expected_covered_person_version`; supersedes an existing `DRAFT`/`SUBMITTED`/`RETURNED` plan for the same person and ticker) | Insider |
| GET | `/tenb5-plans/{id}` | Get a plan | Insider, ComplianceOfficer, LegalAdmin |
| GET | `/tenb5-plans` | List plans (paginated; filterable by `covered_person_id`, `status`) | Insider, ComplianceOfficer, LegalAdmin |
| POST | `/tenb5-plans/{id}/submit` | Submit a `DRAFT` or `RETURNED` plan for review | Insider |
| POST | `/tenb5-plans/{id}/decision` | Approve (computes `cooling_off_end`) or return a `SUBMITTED` plan (segregation of duties) | ComplianceOfficer |
| POST | `/tenb5-plans/{id}/action` | `SUSPEND` (from `ACTIVE`), `RESUME` (from `SUSPENDED`), or `TERMINATE` (from `DRAFT`/`ACTIVE`/`SUSPENDED`) | ComplianceOfficer, Insider |
| POST | `/trade-confirmations` | Ingest a broker trade confirmation; runs the matching pass (preclearance, then plan, else flag, auto-open a violation case, and set the compliance hold) | ComplianceOfficer |
| GET | `/trade-confirmations/{id}` | Get a confirmation | Insider, ComplianceOfficer, LegalAdmin |
| GET | `/trade-confirmations` | List confirmations (paginated; filterable by `covered_person_id`, `match_plan_id`, `status`) | Insider, ComplianceOfficer, LegalAdmin |
| POST | `/violation-cases` | Manually open a violation case | ComplianceOfficer |
| GET | `/violation-cases/{id}` | Get a violation case | ComplianceOfficer, LegalAdmin |
| GET | `/violation-cases` | List violation cases (paginated; filterable by `covered_person_id`, `trade_confirmation_id`, `status`) | ComplianceOfficer, LegalAdmin |
| POST | `/violation-cases/{id}/action` | Advance a case: `BEGIN_INVESTIGATION`, `ESCALATE`, `DEESCALATE`, `SUBSTANTIATE`, `UNFOUND`, `RECORD_SANCTION`, or `CLOSE` | ComplianceOfficer |
| POST | `/attestations` | Assign a policy acknowledgment or annual training | LegalAdmin |
| GET | `/attestations/{id}` | Get an attestation | Insider, ComplianceOfficer, LegalAdmin |
| GET | `/attestations` | List attestations (paginated; filterable by `covered_person_id`, `kind`, `status`) | Insider, ComplianceOfficer, LegalAdmin |
| POST | `/attestations/{id}/complete` | Complete an attestation (from `ASSIGNED` or `OVERDUE`) | Insider |
| POST | `/compliance-sweeps` | Run the compliance sweep in the pinned order of §2.10 | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is the index of identifiers and statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SELF_ACTION_FORBIDDEN` | 403 |
| `ERR_SECURITY_RESTRICTED` | 422 |
| `ERR_COMPLIANCE_HOLD` | 422 |
| `ERR_TRADE_IN_BLACKOUT` | 422 |
| `ERR_DATE_RANGE_INVALID` | 422 |
| `ERR_POLICY_ACK_REQUIRED` | 422 |
| `ERR_TRAINING_OVERDUE` | 422 |
| `ERR_DUPLICATE_VOTE` | 409 |
| `ERR_DUPLICATE_QUARTER_WINDOW` | 409 |
| `ERR_DUPLICATE_RESTRICTED_ENTRY` | 409 |
| `ERR_OVERLAPPING_APPROVAL` | 409 |
| `ERR_QUANTITY_EXCEEDS_APPROVED` | 422 |
| `ERR_CASE_ALREADY_OPEN` | 409 |
