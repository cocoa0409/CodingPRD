# Business Entity Formation API — Product Requirements Document

## 1. Introduction

State-level business formation has long been an exercise in paperwork serialization. A founder forms an LLC, mails a separately-signed operating agreement, queues for an EIN, designates a registered agent in the home state, files an annual report each spring, qualifies in a sister state to open a regional office, and — increasingly — discloses beneficial owners on a federally-driven schedule. Each artifact is independently produced and independently mailed, yet they form a single compliance posture: a missing registered agent quietly dissolves the company's ability to receive service of process; a missed annual report quietly cascades into delinquency, suspension, and eventual administrative dissolution; an out-of-date BOI filing quietly disqualifies the entity from a foreign qualification even though every other obligation is current. The state office sees only the artifact in front of it; the filer sees only the form they are filling out today.

This API consolidates the lifecycle of a state-chartered business entity — formation, governance documents, federal tax identifier, statutory representation, annual reporting, out-of-state qualification, and beneficial-owner disclosure — under a single posture-driven model. Every mutation re-evaluates the parent `BusinessEntity`'s compliance posture from its current child set; every child action checks the parent's posture before it is allowed to land. Time itself is treated as a first-class input via a test-driving clock endpoint, because most of the failure modes a real registrar cares about (April-15 delinquency, ninety-day BOI grace, two-consecutive-year administrative suspension) only emerge when the calendar advances. The result is a single source of truth that both filers and state reviewers can consult to know, at any instant, whether an entity is in good standing and which obligations must be discharged to keep it there.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than the formation-creation endpoint, the public-registry reads on `BusinessEntity` (`GET /business-entities` and `GET /business-entities/{id}`), and the test-driving clock endpoint must carry two headers: `X-User-ID` (the caller's identifier) and `X-User-Role` (the caller's role string). On those header-optional endpoints a caller that omits both headers entirely is treated as `Anonymous` (which is on each of their authorized role lists); a caller that supplies one header without the other, or supplies an unrecognized role string, is still rejected. Missing, empty, or unrecognized auth headers on every other endpoint are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not on the target endpoint's authorized list is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles, written here with the exact capitalization the API requires:

- `Anonymous` — a pre-formation requester with no persisted identity. `X-User-ID` is an opaque token not tied to any stored entity; the server does not compare it to any record's `id`. `Anonymous` can create a new `BusinessEntity` and read the public formation registry, and nothing else.
- `Filer` — the person operating on behalf of one specific `BusinessEntity`. When `X-User-Role` is `Filer`, `X-User-ID` is the `id` of the acting `BusinessEntity`; ownership checks on any resource that references a `BusinessEntity` compare the resource's `business_entity_id` to `X-User-ID`. A `Filer` may only mutate children of the `BusinessEntity` they identify as.
- `StateAdmin` — the state-office reviewer. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it in audit context but does not compare it to any entity's `id`. The role handles EIN issuance, foreign-qualification approval, reinstatement from suspension, and the test-driving clock.
- `ComplianceOfficer` — the audit and correction role. `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The role's primary capability is voiding a previously-filed annual report and, like `StateAdmin`, driving the synthetic clock.

The exception to authentication is the open formation endpoint (an unrelated party with no prior entity can charter a new `BusinessEntity`); the clock-advance endpoint still requires the same `X-User-ID` and `X-User-Role` headers as any other authenticated endpoint with a role from `StateAdmin` or `ComplianceOfficer` (so missing or unrecognized headers there return `ERR_UNAUTHENTICATED`), and is exempted only from the entity-ownership check because no entity is being mutated by it.

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

List endpoints accept two integer query parameters, `limit` and `offset`, both optional. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; `offset` defaults to 0 and has no upper bound beyond the underlying collection size. Results are always ordered by `created_at` ascending — list responses are stable across calls when no new resource has been created. The response `meta` includes `limit`, `offset`, `total_count` (the total matching row count across all pages), and `has_more` (true when more results exist past the returned window).

### 2.4. Common Resource Properties

Every resource other than `ComplianceEvent` carries four common fields that the API mints and maintains on the server side. The `id` is a server-minted UUID string; it never carries a type prefix, never echoes any input, and is the sole stable identifier for cross-resource references. The `created_at` and `updated_at` timestamps are ISO 8601 UTC strings with three fractional digits — `created_at` is stamped at insert time and never changes thereafter, `updated_at` is restamped on every mutation. The `version` is an integer that starts at 1 on insert and increments by exactly 1 on every successful mutation of that resource; whenever a side effect cascade restates a `version`, the increment is also by 1.

`ComplianceEvent` is the lone exception: it is an immutable audit row carrying only `id`, `business_entity_id`, `event_type`, `event_payload`, and the server-stamped `event_at` timestamp. It has no `updated_at` and no `version`, because compliance events are never rewritten — they are inserted and then read.

The `event_at` timestamp of a `ComplianceEvent` reflects the current clock UTC at the instant of emission, which in test scenarios is the value most recently set through the clock-advance capability (see §3.7).

### 2.5. Nested Resource Retrieval and Path Validation

Nested URLs are validated left to right. When a path looks like `/business-entities/{business_entity_id}/foreign-qualifications/{foreign_qualification_id}`, the parent `BusinessEntity` is resolved first; if it does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) regardless of whether the child id would have been valid. Once the parent resolves, the child is resolved next, and the child's `business_entity_id` foreign key must match the path parent — a mismatch is also `ERR_NOT_FOUND`. Foreign-key fields in request payloads (for example `foreign_registered_agent_id`) follow the same rule: an unresolvable reference returns `ERR_NOT_FOUND`, not a downstream validation error.

### 2.6. Monetary Precision and Date Arithmetic

All monetary amounts are tracked in integer cents — there is no floating-point representation anywhere in the system. The franchise-tax base computation uses integer floor division on its single intermediate step (the per-dollar scaling of base by the revenue-band multiplier), and the late-fee per-day computation uses round-half-up at exactly one point (converting the per-day rate hundredths back into integer cents) before the integer multiplication by days, so the per-day rounding is fixed and the totals are deterministic. Date arithmetic for the BOI deadline is whole-day at UTC; the deadline comparison is inclusive on the deadline second.

### 2.7. Optimistic Concurrency on the BusinessEntity Version

Exactly one write endpoint participates in optimistic concurrency control, and the rule is precisely scoped. A new `RegisteredAgent` creation request must carry a non-optional field `expected_business_entity_version` whose value is the `version` of the target `BusinessEntity` as the client last observed it. The server compares that value to the `BusinessEntity`'s current `version` at the moment of the write; if they do not match — that is, if some other writer has advanced the `BusinessEntity`'s `version` between the client's read and the client's write — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The rule exists because creating a new agent legitimately supersedes the prior `ACTIVE` agent in the same request, and the only way to detect that the client formed its supersede intent against a stale view of the entity is to OCC-gate on the parent's `version`. No other endpoint reads or requires `expected_business_entity_version`, and other writes do not accept the field.

### 2.8. The Compliance Posture Principle

`compliance_posture` is the API's central derived field. It is recomputed on every write that mutates a `BusinessEntity` or any of its children — every state transition, every new child creation, every clock advance that knocks a draft report into delinquency. The posture is a single enum on the parent (`GOOD_STANDING`, `RESTRICTED`, or `FROZEN`) but its value is determined by the union of child states, so the parent's posture cannot drift from its children. Posture itself is a gate on certain operations (notably foreign-qualification approval), which makes the recomputation pass also a permission-gate refresh. The full derivation rule lives in §3.6 alongside the related cascades.

### 2.9. The Time-as-Input Principle

Several of the most consequential state transitions are time-driven: an annual report flips from `DRAFT` to `DELINQUENT` when the calendar advances past April 15 of the year after the reporting year; a beneficial-owner disclosure must be submitted before its filing deadline; an entity that remains delinquent across two consecutive years is administratively suspended; and a posture snapshot for a historical year reads each child as of December 31 of that year. To make these transitions testable without waiting on wall-clock time, the system exposes a test-driving capability that pins the server's notion of "now" to an arbitrary ISO 8601 UTC instant supplied by the caller. Setting the clock also retroactively re-evaluates time-gated transitions: any `AnnualReport` still in `DRAFT` whose deadline has now passed flips to `DELINQUENT`, and the parent `BusinessEntity` cascades accordingly. Every timestamp the server stamps thereafter — including `event_at` on emitted `ComplianceEvent` rows — derives from the pinned clock rather than wall time.

### 2.10. Validation Priority Ordering

A single request can fail multiple checks; the API guarantees a fixed priority of evaluation so that the surfaced error is always the most foundational reason for rejection. The order is, from highest to lowest priority: authentication (`ERR_UNAUTHENTICATED`) first, then role authorization (`ERR_UNAUTHORIZED`), then existence/foreign-key resolution (`ERR_NOT_FOUND`), then state-machine legality (`ERR_INVALID_STATE`), then the dissolved-parent gate (`ERR_ENTITY_DISSOLVED`), then payload safety checks (BOI and operating-agreement member-list checks), then referential business rules (foreign-qualification agent matching, in-state agent matching), then temporal uniqueness rules (annual-report period uniqueness, foreign-qualification interval overlap), then business-constraint rules (BOI deadline, foreign-state difference, operating-agreement template match), then fiscal rules (franchise-tax cap, franchise-tax arrears), and finally the optimistic-concurrency check (`ERR_STALE_VERSION`). When two payload-shape problems coexist with a missing path id, the path id error surfaces first; when an operating-agreement is submitted against a `FROZEN` entity with both a bad template type and a bad member list, the dissolved/state-gate fires before the safety checks. Treat the listed order as binding, not advisory.

## 3. Business Logic & Workflows

### 3.1. Forming the Entity

A `BusinessEntity` is the root of every other artifact in the system, and the only resource an `Anonymous` caller may create. The formation payload supplies the entity's `legal_name`, its `entity_type`, its `formation_state_code`, and optionally its `revenue_band`. The `legal_name` is between 1 and 200 characters long and may contain uppercase ASCII letters, digits, spaces, hyphens, periods, commas, and ampersands — names with lowercase letters or unlisted punctuation are rejected with `ERR_INVALID_REQUEST`, as is a `legal_name` whose length falls outside the 1-to-200-character window. Within a single `formation_state_code`, the `legal_name` must be unique across all non-dissolved entities. The `entity_type` is one of `LLC`, `CORP`, or `LP`; the `formation_state_code` is a two-letter uppercase code drawn from the supported set `CA`, `DE`, `NY`, `TX`, `FL`, and `WY`; any other code is `ERR_INVALID_REQUEST`. The optional `revenue_band` selects the franchise-tax tier and is one of `ZERO`, `MICRO`, `SMALL`, `MEDIUM`, or `LARGE`; when omitted the entity defaults to `ZERO`.

On creation the entity is persisted with `status` set to `FORMING`, `compliance_posture` provisionally set to `GOOD_STANDING`, `franchise_tax_paid_through_year` initialized to 0, and `cumulative_franchise_tax_paid_cents` initialized to 0. The server stamps `formed_at` from the current clock UTC and returns the created resource. A `FORMING` entity is not yet operational — it cannot file reports, qualify out of state, or submit beneficial-owner disclosures until it becomes `ACTIVE` (see §3.2).

### 3.2. Becoming Active

The transition from `FORMING` to `ACTIVE` is automatic and posture-shaped. The system advances the `BusinessEntity` from `FORMING` to `ACTIVE` the moment three conditions hold simultaneously: there is exactly one `RegisteredAgent` in `ACTIVE` status for the entity; there is exactly one `EINApplication` in `ISSUED` status for the entity; and, if the `entity_type` is `LLC` or `LP`, at least one `OperatingAgreement` for the entity is in `EXECUTED` status. A `CORP` entity does not require an operating agreement and crosses the activation threshold on agent-plus-EIN alone. Because the trigger is automatic and gated on three independent child operations, the activating write — the third of the three to land — is itself the one that promotes the parent: the issuance of an EIN can activate the entity, as can the execution of an operating agreement, as can the creation of the first registered agent. Each side-effect cascade recomputes `compliance_posture` (typically yielding `GOOD_STANDING`), emits a `ComplianceEvent` with `event_type` of `STATUS_CHANGED` carrying an `event_payload` of `{from: FORMING, to: ACTIVE}`, and increments the parent's `version` by 1.

The state machine on `BusinessEntity` is otherwise austere: an `ACTIVE` entity can become `DELINQUENT` (a child annual report has fallen past its deadline), a `DELINQUENT` entity can return to `ACTIVE` (every delinquent report for a year strictly less than the current clock year is now in `FILED` or `VOIDED`), a `DELINQUENT` entity can drop to `SUSPENDED` (two consecutive `period_year` values of delinquent reports), a `SUSPENDED` entity can be reinstated to `ACTIVE` by a `StateAdmin`, and either `ACTIVE` or `DELINQUENT` can transition to `DISSOLVED` on the filer's voluntary dissolve. `DISSOLVED` is terminal — no further child mutation is permitted on a dissolved parent, and any such attempt is rejected with `ERR_ENTITY_DISSOLVED`.

### 3.3. Statutory Representation

Every state demands that an entity name a registered agent on whom service of process can be effected. The `RegisteredAgent` resource is created against a `BusinessEntity` and carries the agent's `agent_name` (1–200 characters), the `agent_type` (one of `INDIVIDUAL` or `COMMERCIAL`), the `agent_state_code` (a two-letter uppercase state code from the supported set), and the `expected_business_entity_version` for OCC. Status begins at `ACTIVE` and the terminal state is `RESIGNED`.

An in-state agent — that is, an agent created with the intent of serving the home-state entity — must carry an `agent_state_code` equal to the entity's `formation_state_code`. A mismatch is rejected with `ERR_AGENT_STATE_MISMATCH`. Foreign-state agents (those whose `agent_state_code` differs from `formation_state_code`) are created with the same endpoint but are only consumable as the `foreign_registered_agent_id` of a `ForeignQualification` — they do not satisfy the home-state coverage requirement and never count toward the activation precondition for the parent. Wherever this PRD speaks of "an `ACTIVE` `RegisteredAgent` for the parent" or counts ACTIVE registered agents (notably the `compliance_posture` derivation in §3.6, the activation precondition in §3.2, the filing precondition in §3.7, the BOI-submit precondition in §3.11, and the reinstatement precondition in §3.6), it refers to the home-state slot only — that is, agents whose `agent_state_code` equals the parent's `formation_state_code`. ACTIVE foreign-state agents are not counted by any of those checks, and multiple ACTIVE foreign-state agents may coexist on the same parent without conflicting with one another.

The agent-creation endpoint operates under a CREATE-with-supersede contract that is scoped to the home-state slot: if the new agent is a home-state agent (`agent_state_code` equals `formation_state_code`) and the parent already has a home-state agent in `ACTIVE`, that prior home-state agent is transitioned from `ACTIVE` to `RESIGNED` in the same request, the new agent is persisted in `ACTIVE`, the parent's `compliance_posture` is recomputed, and a `ComplianceEvent` with `event_type` of `AGENT_REPLACED` is emitted to mark the supersession. Creating a foreign-state agent never supersedes any existing agent (home-state or foreign-state) and never emits `AGENT_REPLACED`; creating a home-state agent never resigns any foreign-state agent. The supersede increments the parent's `version` by 1; the entity's automatic `FORMING → ACTIVE` transition may fire on the same write if it is now eligible. The `expected_business_entity_version` field guards this race: if a prior writer has already advanced the parent's `version` since the client last read it, the new agent creation is rejected with `ERR_STALE_VERSION` (HTTP 412) so the client cannot silently overwrite the supersede it has not observed.

Voluntary resignation is the other path out of `ACTIVE`. A `Filer` can resign a `RegisteredAgent`; the resource transitions from `ACTIVE` to `RESIGNED`, `resigned_at` is stamped from the current clock UTC, the agent's own `version` is incremented by 1, and the parent's `compliance_posture` is recomputed in place. The recomputation is a posture-only refresh: the parent's `version` and `updated_at` are not advanced by a voluntary resignation (only by the supersede path in the preceding paragraph or by an automatic status cascade). With no `ACTIVE` agent left, the posture typically falls to `RESTRICTED`. A voluntary resignation does not emit an `AGENT_REPLACED` event — that event is reserved for the supersession cascade — and no `STATUS_CHANGED` event is emitted unless an automatic parent-status cascade fires as part of the same write.

### 3.4. The Operating Agreement Ladder

An `OperatingAgreement` is the governance document for an `LLC` or an `LP`; `CORP` entities do not produce one and any attempt to create an operating agreement against a `CORP` parent is rejected with `ERR_TEMPLATE_TYPE_MISMATCH`. The create payload supplies the `template_type` and a `members_json` array of `{name, ownership_pct}` entries. The permitted templates are `MEMBER_MANAGED` and `MANAGER_MANAGED` for `LLC` parents, and `LP_GENERAL_LIMITED` for `LP` parents; any other pairing fails the same template-mismatch error.

The `members_json` array carries between 1 and 50 entries; each member's `name` is 1–120 characters and each `ownership_pct` is an integer between 1 and 100. The sum of all members' `ownership_pct` values must equal exactly 100 — neither 99 nor 101 is acceptable. Violations of any of these member-list rules are rejected with `ERR_OPERATING_AGREEMENT_INVALID`.

A newly created operating agreement enters `DRAFT`. Executing it advances the resource from `DRAFT` to `EXECUTED`, stamping `executed_at` from the current clock UTC. The execute call re-validates the member-list integrity in case the agreement was created before a future field-level rejection rule was tightened; it also requires that the parent `BusinessEntity` is not `DISSOLVED` (a dissolved parent fails the call with `ERR_ENTITY_DISSOLVED`) and that its `compliance_posture` is not `FROZEN` (a `FROZEN` posture on a non-dissolved parent fails the call with `ERR_INVALID_STATE`). If the parent already had a prior `EXECUTED` operating agreement, that prior one is transitioned to `SUPERSEDED` in the same request — the supersession is a silent system step that emits no event, since the new `EXECUTED` record is itself the audit trail. The execution may, as a side effect, drive the parent's automatic `FORMING → ACTIVE` transition if doing so brings the three activation preconditions together. Every successful execution increments the operating agreement's `version` by 1.

`SUPERSEDED` is the terminal state for an operating agreement — once an agreement is superseded by a later execution, it can no longer be re-executed or modified.

### 3.5. The EIN Application

An `EINApplication` is the federal-tax-identifier petition. It is created against a `BusinessEntity` by a `Filer` and carries the `responsible_party_name` (1–120 characters) and `responsible_party_ssn_last4` (exactly four decimal digits, including leading zeros — represented as a string for this reason). The application is persisted in `PENDING` status with `ein` null and `issued_at` null.

A `StateAdmin` acts on the application: by default the call advances it from `PENDING` to `ISSUED`, at which point the server mints a nine-digit `ein` in the form `NN-NNNNNNN` (the leading two digits, a dash, then seven trailing digits) — concretely the server uses the fixed prefix `87` followed by a process-local monotonically incrementing seven-digit sequence zero-padded from `0000001`, so the first issued EIN is `87-0000001`, the second `87-0000002`, and so on — stamps `issued_at` from the current clock UTC, and increments the application's `version` by 1. The same call can instead reject the application by passing `reject` set to true in the payload, which advances the resource from `PENDING` to `REJECTED` without minting an EIN. Both `ISSUED` and `REJECTED` are terminal — the application cannot be re-acted on. An issuance may carry the parent's `FORMING → ACTIVE` cascade if the parent's other activation preconditions are now satisfied. Issuance is not permitted on a `DISSOLVED` parent.

### 3.6. The Compliance Posture and Its Cascades

`compliance_posture` is the aggregate gate that determines whether the parent can accept various child operations. Its derivation is a strict priority cascade: if the parent's `status` is `DISSOLVED`, the posture is `FROZEN`; otherwise if `status` is `SUSPENDED`, the posture is `FROZEN`; otherwise if any `AnnualReport` for the parent is in `DELINQUENT` status, the posture is `RESTRICTED`; otherwise if no `RegisteredAgent` for the parent is in `ACTIVE` status, the posture is `RESTRICTED`; otherwise if any `BOIDisclosure` exists for the parent and the most-recent `submitted_at` plus 365 days falls strictly before the current clock UTC, the posture is `RESTRICTED`; otherwise the posture is `GOOD_STANDING`. The 365-day refresh window is the BOI staleness rule — a `BOIDisclosure` that has not been re-submitted within one year of its last submission allows the posture to drift to `RESTRICTED` even when every other obligation is current.

The posture also has a snapshot variant. The historical-posture read substitutes the current clock UTC with the December 31 23:59:59 UTC instant of a supplied calendar year and evaluates each child's state as of that timestamp — an `AnnualReport` that was still `DRAFT` at year-end was therefore not yet `DELINQUENT` in the snapshot, even if it has since flipped. The snapshot is what underpins year-end compliance certificates and never reads "now".

The cascades that feed posture are anchored in `BusinessEntity` state transitions. When a `DRAFT` annual report flips automatically to `DELINQUENT` (the deadline-driven transition described in §3.7), the parent is recomputed: `compliance_posture` moves to `RESTRICTED` and, if the parent was `ACTIVE`, its `status` also flips to `DELINQUENT` (the second hop of the cascade). When every delinquent report has been cured for every `period_year` strictly less than the current clock year, the parent's `status` automatically returns from `DELINQUENT` to `ACTIVE` and the posture is recomputed toward `GOOD_STANDING`. When delinquency persists across two consecutive `period_year` values, the parent transitions from `DELINQUENT` to `SUSPENDED` and the posture freezes; a `StateAdmin` may later reinstate the entity (`SUSPENDED → ACTIVE`) provided every delinquent report whose `period_year` is strictly less than the current clock year is now in `FILED` or `VOIDED` and exactly one `RegisteredAgent` is in `ACTIVE`. Calling reinstate on an entity whose `status` is anything other than `SUSPENDED`, or while any of the preceding preconditions is unmet, is rejected with `ERR_INVALID_STATE`. Each `BusinessEntity` transition emits a corresponding `ComplianceEvent`: ordinary status changes emit `event_type` of `STATUS_CHANGED` with `event_payload` of `{from: X, to: Y}`, while the reinstatement-driven `SUSPENDED → ACTIVE` transition emits `event_type` of `REINSTATED` carrying the same payload shape.

### 3.7. Annual Reports, the Clock, and Delinquency

An `AnnualReport` is created by a `Filer` against a `BusinessEntity` with a single payload field: `period_year`, an integer between 2020 and 2099 inclusive. At most one report may exist per `(business_entity_id, period_year)` pair across the entire lifetime of the entity — even a `VOIDED` report occupies that slot, so re-creation against the same period is rejected with `ERR_REPORT_PERIOD_TAKEN`. On creation the report enters `DRAFT` and the server stamps a provisional `franchise_tax_amount_cents` (the provisional estimate variant described in §3.8); `late_fee_cents` starts at 0, and both `filed_at` and `voided_at` are null.

Annual reports are time-sensitive. The deadline for filing a report covering `period_year` is the April 15 23:59:59 UTC instant of `period_year + 1`. Whenever the current clock UTC moves strictly past that deadline and the report is still in `DRAFT`, the system flips the report automatically from `DRAFT` to `DELINQUENT`, recomputes the parent's `compliance_posture` toward `RESTRICTED`, and — if this is the first delinquent report on a parent that was `ACTIVE` — also drives the parent's `ACTIVE → DELINQUENT` cascade. A `ComplianceEvent` with `event_type` of `DELINQUENT_AUTO` is emitted for the report, the report's `version` is incremented by 1, and the parent's `STATUS_CHANGED` event records its own status flip if it occurred. The deadline check is strict-greater-than: a filing landing exactly on the deadline second is on time and does not flip.

Because real wall time would make these flips untestable, the API exposes a `StateAdmin` and `ComplianceOfficer` capability that sets the server's current clock UTC to a supplied `to_iso8601` instant. Pinning the clock immediately re-evaluates every `AnnualReport` in `DRAFT` and triggers the deadline-driven flips. The capability is the only path by which the test harness can simulate the passage of time; the resulting cascades are otherwise identical to those that would occur under real wall-clock advance. The clock endpoint returns HTTP 200 with a `data` object of the shape `{"current_utc": "<the pinned ISO 8601 UTC instant>"}`; no resource is mutated and no `ComplianceEvent` is emitted by the act of setting the clock itself (only the time-driven transitions it unblocks emit events).

Filing a report — moving it from either `DRAFT` or `DELINQUENT` to `FILED` — re-evaluates the assessed franchise tax against the parent's current `revenue_band` (the assessed-final variant in §3.8), computes the `late_fee_cents` from the current clock UTC against the deadline (§3.9), stamps `filed_at` from the current clock UTC, recomputes the parent's `franchise_tax_paid_through_year` (the maximum `period_year` across all `FILED` reports) and `cumulative_franchise_tax_paid_cents` (the sum of `franchise_tax_amount_cents` plus `late_fee_cents` across all `FILED` reports), and may drive the parent's automatic `DELINQUENT → ACTIVE` transition if every other delinquent report has now been cured. A `ComplianceEvent` with `event_type` of `REPORT_FILED` is emitted, and the report's `version` is incremented by 1. Filing requires that exactly one `RegisteredAgent` for the parent is in `ACTIVE` status; without statutory representation the report cannot land and the call is rejected with `ERR_INVALID_STATE`. Filing is permitted on a `SUSPENDED` parent because filing the delinquent reports is the prerequisite cure for reinstatement, but on any other non-`DISSOLVED` parent whose `compliance_posture` is `FROZEN` the call is rejected with `ERR_INVALID_STATE`.

A `ComplianceOfficer` may void a `FILED` report as a correction path: the report transitions from `FILED` to `VOIDED`, `voided_at` is stamped from the current clock UTC, the parent's `franchise_tax_paid_through_year` and `cumulative_franchise_tax_paid_cents` are recomputed, a `ComplianceEvent` with `event_type` of `REPORT_VOIDED` is emitted, and the report's `version` is incremented by 1. The invariant that governs the void-then-refile path is that a later refile must restore the parent's cumulative-tax totals to exactly what they were before the void — voiding then refiling the same period with the same `revenue_band` and the same filing instant is monetarily transparent.

### 3.8. Franchise Tax Computation

The franchise tax is a two-input calculation. The first input is a state-and-type base: California charges 800 dollars for every entity type, Delaware charges 300 dollars for `LLC` and `LP` entities and 175 dollars for a `CORP`, New York charges a flat 25 dollars across types, Texas charges nothing, Florida charges 138.75 dollars for an `LLC`, 150 dollars for a `CORP`, and 500 dollars for an `LP`, and Wyoming charges 60 dollars for `LLC` and `CORP` and 100 dollars for `LP`. All bases are tracked in integer cents (so 800 dollars is 80000 cents, 138.75 dollars is 13875 cents). The second input is a revenue-tier multiplier, expressed as a hundredths-scaled integer: `ZERO` and `MICRO` are 1.00x (multiplier 100), `SMALL` is 1.10x (multiplier 110), `MEDIUM` is 1.25x (multiplier 125), and `LARGE` is 1.50x (multiplier 150).

The raw amount is the base in cents multiplied by the tier multiplier, then divided by 100 with integer floor — that is, any fractional cent introduced by the multiplier is dropped, not rounded. The result is then floored from below by a per-state assessed-variant minimum: California 80000 cents, Delaware 17500 cents, New York 2500 cents, Texas 0 cents, Florida 13875 cents, Wyoming 6000 cents. The final `franchise_tax_amount_cents` is the larger of the raw amount and the state's minimum floor. The arithmetic is all in integer cents; no rounding is applied at the multiply-and-floor step.

The calculation has two variants that share the same formula but differ in when they read `revenue_band`. The provisional-estimate variant runs at report creation and reads `revenue_band` as declared on the parent at that moment, stamping the provisional `franchise_tax_amount_cents`. The assessed-final variant runs at filing time and re-reads `revenue_band` as currently declared on the parent, possibly producing a different number than the provisional estimate if the band has been changed in between. The assessed-final value is the binding one — it is what gets written to `franchise_tax_amount_cents` on the report and what feeds the parent's `cumulative_franchise_tax_paid_cents`.

There is a cumulative-tax safety cap fixed at 1,000,000,000 cents (10,000,000 dollars). When filing a report, the assessed `franchise_tax_amount_cents` plus the `late_fee_cents` of that filing must, when added to the parent's existing `cumulative_franchise_tax_paid_cents`, leave the running total strictly less than that cap; an attempt that would equal or exceed the cap is rejected with `ERR_FRANCHISE_TAX_CAP_EXCEEDED`.

### 3.9. Late-Fee Accrual

The late-fee computation runs at the filing instant. The deadline for `period_year` is, as in §3.7, the April 15 23:59:59 UTC instant of `period_year + 1`. When the current clock UTC at filing is at or before that deadline, `late_fee_cents` is 0 and no accrual occurs. When the current clock UTC at filing is strictly past the deadline, the system computes the difference in whole seconds, then converts to days-late by ceiling division — any partial day counts as a full day, and the minimum days-late is 1. The per-state daily rate is expressed in hundredths of a cent: California 55.50 cents per day (rate-hundredths 5550), Delaware 111.00 cents per day (11100), New York 22.50 cents per day (2250), Texas no late fee at all (0), Florida 77.75 cents per day (7775), and Wyoming 33.25 cents per day (3325). The per-day fee in integer cents is the daily rate plus 50 hundredths divided by 100 with integer floor — that is, the per-day rate is rounded half-up to cents before any multiplication. The accrued amount is then the per-day fee in integer cents multiplied by the integer days-late count. The order is pinned: per-day rounding occurs first, then the multiplication by days-late; the alternative of summing the per-day rate over all days and then rounding once is forbidden, because it produces a different total for non-trivial day counts. Finally, the accrued amount is capped at 25,000,000 cents (250,000 dollars); any larger accrual is clipped down to the cap, so the late fee is the minimum of the accrued amount and the cap.

### 3.10. Foreign Qualification

A `BusinessEntity` that wishes to do business in a state other than its `formation_state_code` files a `ForeignQualification`. The creation payload supplies `foreign_state_code` and `foreign_registered_agent_id`. The `foreign_state_code` is a two-letter uppercase state code from the supported set and must differ from the parent's `formation_state_code` — qualifying against your own home state is `ERR_FQ_SAME_STATE`. The `foreign_registered_agent_id` references a `RegisteredAgent`, which must be in `ACTIVE` status and whose `agent_state_code` must equal the `foreign_state_code`; failures of either condition are rejected with `ERR_FQ_AGENT_MISMATCH`.

A newly-created qualification enters `PENDING`. A `StateAdmin` then approves it (`PENDING → QUALIFIED`), at which point `qualified_at` is stamped from the current clock UTC, a `ComplianceEvent` with `event_type` of `FQ_QUALIFIED` is emitted, and the qualification's `version` is incremented by 1. Approval imposes several additional gates beyond the create-time checks: the parent's `compliance_posture` must be `GOOD_STANDING` (a `RESTRICTED` or non-dissolved `FROZEN` posture is rejected with `ERR_INVALID_STATE`, and a posture of `FROZEN` driven by `status=DISSOLVED` is rejected with `ERR_ENTITY_DISSOLVED`), the foreign agent's `ACTIVE` and `agent_state_code` constraints are re-verified at approval time, no other `QUALIFIED` `ForeignQualification` for the same `(business_entity_id, foreign_state_code)` pair whose half-open `[qualified_at, withdrawn_at)` interval covers the current clock UTC may exist (overlap is rejected with `ERR_FQ_OVERLAP`), and every prior `AnnualReport` for the parent whose `period_year` is strictly less than the current clock year must already be in `FILED` or `VOIDED` (an arrears report blocks approval with `ERR_FRANCHISE_TAX_IN_ARREARS`).

A `Filer` may withdraw a `QUALIFIED` qualification (`QUALIFIED → WITHDRAWN`). `withdrawn_at` is stamped from the current clock UTC, a `ComplianceEvent` with `event_type` of `FQ_WITHDRAWN` is emitted, and the qualification's `version` is incremented by 1. `WITHDRAWN` is terminal. Dissolution of the parent is gated on the absence of any `QUALIFIED` foreign qualification — the filer must withdraw each one before dissolving.

### 3.11. Beneficial-Owner Disclosure and Its Deadline

A `BOIDisclosure` is created by a `Filer` against a `BusinessEntity` with a payload carrying `triggering_event` and `beneficial_owners_json`. The `triggering_event` is one of `FORMATION`, `AMENDMENT`, or `ANNUAL_REFRESH` and determines which calendar base and grace window the deadline computation uses. The `beneficial_owners_json` is an array of between 1 and 25 entries, each consisting of `name`, `dob`, `ownership_pct` (integer between 1 and 100), and `control_role` (one of `OWNER`, `CONTROLLER`, or `BOTH`); the sum of all owners' `ownership_pct` values must equal exactly 100. A bad owner count, a bad ownership percentage, a bad sum, or a bad `control_role` is rejected with `ERR_BOI_INVALID`.

The filing deadline is a derived, read-only field named `boi_filing_deadline` returned on every response that carries a `BOIDisclosure` body (the create response, the submit/amend transition responses, and the list/read responses), formatted as an ISO 8601 UTC timestamp string. When the `triggering_event` is `FORMATION`, the deadline base is the parent's `formed_at` and the grace window is 90 whole days. When the `triggering_event` is `AMENDMENT` or `ANNUAL_REFRESH`, the deadline base is the current clock UTC at the disclosure's creation moment and the grace window is 30 whole days. The day arithmetic is whole-day at UTC; the deadline is the base instant plus the appropriate number of days. The deadline comparison is inclusive on the deadline second — a submission landing at exactly the deadline second is on time. A submit attempted past the deadline is rejected with `ERR_BOI_PAST_DEADLINE`.

A new disclosure enters `DRAFT`. The filer submits it (`DRAFT → SUBMITTED`), at which point `submitted_at` is stamped from the current clock UTC, a `ComplianceEvent` with `event_type` of `BOI_SUBMITTED` is emitted, and the disclosure's `version` is incremented by 1. Submission re-checks the member-list integrity, requires that the parent's `status` is not `DISSOLVED` (else `ERR_ENTITY_DISSOLVED`), requires exactly one `RegisteredAgent` in `ACTIVE` for the parent (else `ERR_INVALID_STATE`), and enforces the deadline check (a submit past the deadline returns `ERR_BOI_PAST_DEADLINE`). A previously `SUBMITTED` disclosure may be amended (`SUBMITTED → AMENDED`) with a fresh `beneficial_owners_json` payload — the amended payload is re-validated against the same shape, sum, and `control_role` rules. An `AMENDED` disclosure can then be re-submitted (`AMENDED → SUBMITTED`) by the same submit call, restamping `submitted_at`, re-emitting `BOI_SUBMITTED`, and again incrementing the disclosure's `version` by 1. The cycle is `SUBMITTED ↔ AMENDED ↔ SUBMITTED` indefinitely; there is no terminal state on this resource. The 365-day refresh rule in §3.6 means an entity that does not re-submit its disclosure within a year of its last submission drifts to `RESTRICTED` posture even with no other deficiencies.

### 3.12. Dissolution and the Termination Cascade

Voluntary dissolution is the filer's path to ending the entity. The dissolve call is only legal when the entity's `status` is `ACTIVE` or `DELINQUENT` and no `ForeignQualification` for the entity is in `QUALIFIED` — an outstanding foreign qualification blocks dissolution and must be withdrawn first. Both preconditions (wrong status, or an outstanding `QUALIFIED` `ForeignQualification`) are surfaced as `ERR_INVALID_STATE`. On a legal dissolve, the parent's `status` transitions to `DISSOLVED`, the `compliance_posture` is reset to `FROZEN`, every `AnnualReport` in `DRAFT` or `DELINQUENT` is flipped to `VOIDED`, every `RegisteredAgent` in `ACTIVE` is flipped to `RESIGNED`, a `ComplianceEvent` with `event_type` of `STATUS_CHANGED` and `event_payload` of `{from: ACTIVE, to: DISSOLVED}` (or `{from: DELINQUENT, to: DISSOLVED}`) is emitted, and the parent's `version` is incremented by 1. Once `DISSOLVED`, every subsequent child mutation is rejected with `ERR_ENTITY_DISSOLVED` — the entity becomes read-only.

The audit-trail collection is exposed as a list endpoint that returns `ComplianceEvent` rows under a parent `BusinessEntity`, optionally filtered by `event_type`. The event-type values the server actually emits in this implementation are `STATUS_CHANGED`, `REPORT_FILED`, `AGENT_REPLACED`, `BOI_SUBMITTED`, `FQ_QUALIFIED`, `FQ_WITHDRAWN`, `REPORT_VOIDED`, `REINSTATED`, and `DELINQUENT_AUTO`; `POSTURE_CHANGED` is reserved in the catalog but is never emitted, because posture changes always ride along the parent's `STATUS_CHANGED` row or fall out implicitly from a child-driven cascade. The `event_payload` is a free-form JSON object; the concrete shapes the server emits are: `STATUS_CHANGED` and `REINSTATED` carry `{from, to}` (the pre- and post-transition `BusinessEntity.status` values); `REPORT_FILED` carries `{annual_report_id, period_year, franchise_tax_amount_cents, late_fee_cents}`; `REPORT_VOIDED` and `DELINQUENT_AUTO` carry `{annual_report_id, period_year}`; `AGENT_REPLACED` carries `{registered_agent_id}` (the `id` of the newly-active superseding agent); `BOI_SUBMITTED` carries `{boi_disclosure_id}`; `FQ_QUALIFIED` carries `{foreign_qualification_id, foreign_state_code}`; and `FQ_WITHDRAWN` carries `{foreign_qualification_id}`. The trail is the unrolled history of every cascade described above, ordered as elsewhere by `created_at` ascending.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201 on success; endpoints that read, modify, or transition an existing resource respond with HTTP 200. Errors carry the HTTP status documented in §5 alongside the error envelope of §2.2. The table below is a navigation index — request and response shapes, side effects, and authorization gates are described in the workflows above.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/business-entities` | Create a new business entity (formation). | `Anonymous`, `Filer` |
| GET | `/business-entities/{id}` | Read a single business entity. | `Anonymous`, `Filer`, `StateAdmin`, `ComplianceOfficer` |
| GET | `/business-entities` | List business entities (optional filters: `formation_state_code`, `entity_type`, `status`, `limit`, `offset`). | `Anonymous`, `Filer`, `StateAdmin`, `ComplianceOfficer` |
| PATCH | `/business-entities/{id}/dissolve` | Voluntary dissolution. | `Filer` |
| POST | `/business-entities/{id}/reinstate` | Reinstate a suspended entity. | `StateAdmin` |
| POST | `/business-entities/{id}/registered-agents` | Create a registered agent (CREATE-with-supersede; OCC-gated). | `Filer` |
| GET | `/business-entities/{id}/registered-agents` | List registered agents under an entity (filters: `status`, `limit`, `offset`). | `Filer`, `StateAdmin`, `ComplianceOfficer` |
| GET | `/registered-agents/{id}` | Read a single registered agent. | `Filer`, `StateAdmin`, `ComplianceOfficer` |
| GET | `/registered-agents/{id}/foreign-qualifications` | List foreign qualifications that reference this agent (filters: `status`, `limit`, `offset`). | `Filer`, `StateAdmin`, `ComplianceOfficer` |
| POST | `/registered-agents/{id}/resign` | Voluntary resignation of a registered agent. | `Filer` |
| POST | `/business-entities/{id}/operating-agreements` | Create an operating agreement in `DRAFT` (LLC/LP only). | `Filer` |
| GET | `/business-entities/{id}/operating-agreements` | List operating agreements under an entity (filters: `status`, `limit`, `offset`). | `Filer`, `StateAdmin`, `ComplianceOfficer` |
| POST | `/operating-agreements/{id}/execute` | Execute an operating agreement. | `Filer` |
| POST | `/business-entities/{id}/ein-applications` | Create an EIN application in `PENDING`. | `Filer` |
| GET | `/business-entities/{id}/ein-applications` | List EIN applications under an entity (filters: `status`, `limit`, `offset`). | `Filer`, `StateAdmin`, `ComplianceOfficer` |
| POST | `/ein-applications/{id}/issue` | Issue or reject an EIN application (payload may include `reject`). | `StateAdmin` |
| POST | `/business-entities/{id}/annual-reports` | Create an annual report in `DRAFT` for a `period_year`. | `Filer` |
| GET | `/business-entities/{id}/annual-reports` | List annual reports under an entity (filters: `status`, `period_year`, `limit`, `offset`). | `Filer`, `StateAdmin`, `ComplianceOfficer` |
| POST | `/annual-reports/{id}/file` | File an annual report. | `Filer` |
| POST | `/annual-reports/{id}/void` | Void a filed annual report. | `ComplianceOfficer` |
| POST | `/business-entities/{id}/foreign-qualifications` | Create a foreign qualification in `PENDING`. | `Filer` |
| POST | `/foreign-qualifications/{id}/approve` | Approve a foreign qualification. | `StateAdmin` |
| POST | `/foreign-qualifications/{id}/withdraw` | Withdraw a qualified foreign qualification. | `Filer` |
| GET | `/business-entities/{id}/foreign-qualifications` | List foreign qualifications under an entity (filters: `status`, `foreign_state_code`, `limit`, `offset`). | `Filer`, `StateAdmin`, `ComplianceOfficer` |
| POST | `/business-entities/{id}/boi-disclosures` | Create a BOI disclosure in `DRAFT`. | `Filer` |
| POST | `/boi-disclosures/{id}/submit` | Submit a BOI disclosure. | `Filer` |
| POST | `/boi-disclosures/{id}/amend` | Amend a submitted BOI disclosure. | `Filer` |
| GET | `/business-entities/{id}/boi-disclosures` | List BOI disclosures under an entity (filters: `status`, `limit`, `offset`). | `Filer`, `StateAdmin`, `ComplianceOfficer` |
| GET | `/business-entities/{id}/compliance-events` | List compliance-event audit-trail rows (filters: `event_type`, `limit`, `offset`). | `Filer`, `StateAdmin`, `ComplianceOfficer` |
| POST | `/_clock/set_current_utc` | Test-driving clock advance; pins the server's current UTC to `to_iso8601` and re-evaluates time-gated transitions. | `StateAdmin`, `ComplianceOfficer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ENTITY_DISSOLVED` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BOI_INVALID` | 422 |
| `ERR_OPERATING_AGREEMENT_INVALID` | 422 |
| `ERR_FQ_AGENT_MISMATCH` | 422 |
| `ERR_AGENT_STATE_MISMATCH` | 422 |
| `ERR_REPORT_PERIOD_TAKEN` | 409 |
| `ERR_FQ_OVERLAP` | 409 |
| `ERR_BOI_PAST_DEADLINE` | 422 |
| `ERR_FQ_SAME_STATE` | 422 |
| `ERR_TEMPLATE_TYPE_MISMATCH` | 422 |
| `ERR_FRANCHISE_TAX_CAP_EXCEEDED` | 422 |
| `ERR_FRANCHISE_TAX_IN_ARREARS` | 422 |
