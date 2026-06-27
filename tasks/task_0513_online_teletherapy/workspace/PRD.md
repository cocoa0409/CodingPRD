# Online Teletherapy API — Product Requirements Document

## 1. Introduction

This document specifies the behavior of the Online Teletherapy platform, a subscription-based service that connects people seeking mental-health support with licensed therapists who are authorized to practice in the client's state of residence. The platform shepherds a client from initial sign-up and a structured intake questionnaire, through algorithmic therapist matching, into an ongoing care relationship built on asynchronous messaging and a weekly allotment of live-session credits. Underneath the clinical surface sits a recurring billing engine that applies income-based financial-aid discounts, an account-credit wallet that absorbs cancellation and pause refunds, and a reimbursement-document facility that produces superbills clients submit to their HSA or insurer.

The system is built around several intertwined obligations that frequently pull in different directions: clinical safety (a client in active crisis must be insulated from ordinary workflows), regulatory compliance (a therapist may only treat clients in states where they hold a current license), and financial correctness (every cent of discount, refund, wallet application, and reimbursable value must be reproducible). The lifecycles of the core entities are cyclic rather than linear — a care relationship can be switched to a new therapist and resumed, and a subscription can be paused and brought back to life — so the rules below describe not only forward progress but the loops and cascades that keep dependent records consistent. Because much of the platform's logic is time-sensitive (license expiry, billing renewals, pause auto-resume, scheduled cancellations, credit expiry), the system runs on a controllable logical clock rather than wall-clock time.

This specification is written for the engineers implementing the API. It favors domain reasoning first and the wire-level contract second; where a rule could be read two ways, the prose resolves it explicitly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The platform recognizes exactly four roles: `Client`, `Therapist`, `ClinicalAdmin`, and `BillingAdmin`. When a recognized, authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Two of the roles are tied to persisted entities. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's client foreign key (its `client_id`, or the `client_id` of the resource's parent chain) to `X-User-ID`. When `X-User-Role` is `Therapist`, `X-User-ID` is the `id` of the acting `Therapist`; ownership checks on any resource that references a therapist compare the resource's match `therapist_id` to `X-User-ID`. When such an entity-backed role acts on a resource it does not own — a `Client` whose `X-User-ID` differs from the resource's owning client, or a `Therapist` whose `X-User-ID` differs from the owning match's `therapist_id` — the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The other two roles are operational. When `X-User-Role` is `ClinicalAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. `ClinicalAdmin` owns the clinician-operations surface: therapist onboarding and licensing, match proposal and reassignment, intake clearance, and crisis-escalation management. When `X-User-Role` is `BillingAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, which the server may record but never compares to an entity's `id`. `BillingAdmin` owns the financial surface: subscription billing, financial-aid decisions, and superbills.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items skipped before collecting the page; when omitted it defaults to 0.

Unless a specific endpoint states otherwise, list responses are sorted by the `created_at` timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recorded when the resource is first created, and is itself derived from the logical clock described in §2.10. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value and increments by one on every mutation; it underpins the optimistic-concurrency mechanism in §2.9.

Two entities are intentionally lightweight and carry only `id` and `created_at` — they have neither an `updated_at` nor a `version` field. A `SessionCredit` is one: although its `status` advances through a lifecycle, the credit is treated as an event-sourced token rather than a client-mutable resource, so it exposes no `updated_at` and no `version`. A `Message` is the other: a message is immutable once posted, so it likewise carries only `id` and `created_at`.

### 2.5. Optimistic Concurrency Control and the Logical Clock's Place in It

Two write operations require the caller to prove it is acting on a current view of a parent resource, and they do so by demanding a version field in the request body. These are the only two endpoints that take a version field; every other mutating endpoint omits it entirely.

When a live session is scheduled against a match, the request body must include `expected_match_version` carrying the client's last observed `version` of the target `Match`. The server compares it to that match's current `version`; if they differ — for instance because a prior schedule already advanced the match's version while reserving a credit, possibly exhausting the credit pool — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the caller cannot act on a stale view of the match. Likewise, when a subscription is paused, the request body must include `expected_subscription_version` carrying the client's last observed `version` of the target `Subscription`. The server compares it to the subscription's current `version`; if they differ — for instance because a renewal charge already advanced `current_period_start` since the client last read it — the pause is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a refund computed against a billing period that no longer exists.

### 2.6. Hierarchical Consistency and Cascades

Many operations mutate more than one record. Whenever a state transition fires the side effects described in §3, each affected resource is independently mutated: its `updated_at` is refreshed and, where it carries one, its `version` increments by one. A client moving to its `CLOSED` end-state, for example, is not a single write — it ends every `ACTIVE` match, expires every outstanding credit, and archives every open or frozen message thread, and each of those touched records is itself updated. Implementers must treat each named side effect as a first-class mutation rather than a bookkeeping detail.

Some transitions are driven by the system rather than by an explicit client call on the affected resource. A therapist's roster state flips between `ACCEPTING` and `FULL` automatically as their caseload crosses the cap; a message thread freezes when its match enters a switch request; a client returns from `SUSPENDED` to `ACTIVE` when their crisis is resolved. These server-initiated transitions are described in the workflow narratives of §3 and obey the same per-record mutation rules.

### 2.7. Nested Resource Retrieval and Existence Ordering

Many paths address a resource nested under a parent — a client's intake, a match's live sessions, a subscription's billing cycles, a thread's messages. For any such request, the server validates the path identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. A request for the live sessions of a non-existent match, for example, fails on the match before the system ever considers the sessions. Separately, when a create request carries a foreign key in its body that points to a resource which does not exist, the request is rejected with `ERR_REFERENCED_NOT_FOUND` (HTTP 404).

### 2.8. Money, Credits, and Rounding

All monetary values in the system are integers denominated in cents — base fees, billed amounts, wallet credit, declared income, and reimbursable totals alike. Where a calculation divides or applies a percentage, the result is rounded to whole cents using the round-half-up convention (a value whose fractional cent is exactly one half rounds up to the next whole cent). The financial-aid banding calculation involves only subtraction and therefore needs no rounding; the per-session reimbursable value is taken as a floor rather than a rounded value, as detailed in §3. Wallet credit, billed amounts, and income figures can never go negative — the wallet is constrained to be at least zero at all times.

### 2.9. Enumerated Values

State and category fields draw from fixed vocabularies. A `Client`'s `status` is one of `PENDING_INTAKE`, `AWAITING_MATCH`, `ACTIVE`, `SUSPENDED`, or `CLOSED`; its `financial_aid_tier` is one of `NONE`, `TIER_1`, `TIER_2`, or `TIER_3`; its `risk_flag` is one of `NONE`, `ELEVATED`, or `ACUTE`; and its `state_code` is one of `CA`, `NY`, `TX`, `FL`, `WA`, or `IL`. A `Therapist`'s `status` is one of `ONBOARDING`, `ACCEPTING`, `FULL`, or `INACTIVE`, and each entry in its `specialties` is drawn from `ANXIETY`, `DEPRESSION`, `TRAUMA`, `COUPLES`, `GRIEF`, or `ADHD`. A `TherapistLicense` has a `state_code` from the same six-state set and a `status` of `VALID`, `EXPIRED`, or `REVOKED`. An `IntakeQuestionnaire`'s `presenting_concerns` is a non-empty subset of the same specialty vocabulary. A `Match`'s `status` is one of `PROPOSED`, `ACTIVE`, `SWITCH_REQUESTED`, or `ENDED`, and its `switch_reason` is one of `FIT`, `AVAILABILITY`, `CLINICAL`, or `OTHER` (or null when no switch has been requested). A `Subscription`'s `status` is one of `TRIALING`, `ACTIVE`, `PAUSED`, `CANCEL_SCHEDULED`, or `CANCELLED`. A `BillingCycle`'s `status` is one of `PENDING`, `PAID`, `REFUNDED`, or `VOID`. A `SessionCredit`'s `status` is one of `AVAILABLE`, `RESERVED`, `CONSUMED`, or `EXPIRED`. A `LiveSession`'s `status` is one of `SCHEDULED`, `COMPLETED`, `CANCELLED`, or `NO_SHOW`. A `MessageThread`'s `status` is one of `OPEN`, `FROZEN`, or `ARCHIVED`, and a `Message`'s `sender_role` is either `CLIENT` or `THERAPIST`. A `CrisisEscalation` carries a `raised_by_role` of `CLIENT`, `THERAPIST`, or `SYSTEM`, a `severity` of `ELEVATED` or `ACUTE`, and a `status` of `OPEN`, `ACKNOWLEDGED`, or `RESOLVED`. A `FinancialAidApplication` has a `status` of `SUBMITTED`, `APPROVED`, or `DENIED`, and an `awarded_tier` of `NONE`, `TIER_1`, `TIER_2`, or `TIER_3`. A `Superbill`'s `status` is one of `DRAFT`, `ISSUED`, or `VOID`.

### 2.10. The Logical Clock

The system keeps a logical clock rather than reading wall-clock time, and every timestamp the system mints — `created_at`, `updated_at`, an intake's `submitted_at`, a billing period's boundaries — is read from it. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and until an operator advances it the clock stays at that default and never falls back to real time. An operator can move the clock to any UTC instant by supplying a `to_iso8601` value. Advancing the clock is not a passive act: it recomputes each `TherapistLicense.status` against the new instant, auto-resumes any `PAUSED` subscription whose `pause_resumes_on` is at or before the new instant, auto-finalizes any `CANCEL_SCHEDULED` subscription whose `cancel_effective_on` is at or before the new instant, and expires any `SessionCredit` whose `expires_on` is at or before the new instant. Each of those follow-on transitions fires its own side effects exactly as if it had been triggered directly.

### 2.11. Request Well-Formedness and Validation Ordering

Across every endpoint the platform evaluates a fixed ladder of checks, and the ordering matters because the first failing rung determines which error the caller sees. Authentication comes first: a request lacking valid headers or naming an unknown role fails with `ERR_UNAUTHENTICATED` before anything else. Role permission is evaluated next, yielding `ERR_UNAUTHORIZED` when the role may not perform the operation. Resource ownership follows for the entity-backed roles, yielding `ERR_NOT_RESOURCE_OWNER`. Then path existence is checked left to right, yielding `ERR_NOT_FOUND`, and on create endpoints body foreign keys are checked next, yielding `ERR_REFERENCED_NOT_FOUND`. Only then is the request body inspected for well-formedness — required fields present, enum values within their allowed sets, numbers within range, and on a live session a scheduled end strictly after its start — with any failure raising `ERR_INVALID_REQUEST` (HTTP 400). After a body is judged well-formed, the target resource's current state is checked against the requested transition, raising `ERR_INVALID_STATE` (HTTP 409) when the resource is not in a state from which the transition is legal. Business rules — risk blocks, intake clearance, license coverage, optimistic-concurrency version checks, scheduling conflicts, credit availability, and the rest — are evaluated after these structural rungs, in the priority order their workflows describe. A small class of semantically invalid combinations that survive the basic body check is rejected with `ERR_VALIDATION` (HTTP 422): the prime example is a pause whose requested resume instant lies beyond the permitted horizon, and likewise a `severity_score` that passes its type check but lands outside its permitted numeric span.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding: Registration, Intake, and the Safety Gate

A person joins the platform by self-registering as a `Client`, supplying their `email`, their `full_name`, and the `state_code` of their US state of residence. The email is stored lowercased and must be unique across clients. A newly created client begins in `PENDING_INTAKE` with `financial_aid_tier` of `NONE`, `wallet_credit_cents` of zero, and `risk_flag` of `NONE`; its `wallet_credit_cents` is account credit, expressed in cents and never allowed to drop below zero, that accrues from cancellation and pause refunds and is consumed on the next billing cycle.

The client then submits a single intake questionnaire of record, providing `presenting_concerns` (a non-empty set of concern tags drawn from the specialty vocabulary, which the matcher weighs against therapist specialties), a self-reported `severity_score` between 0 and 10 inclusive, and an optional `crisis_indicator` that defaults to false when omitted. Submission creates an `IntakeQuestionnaire` linked to the client, stamps its `submitted_at` from the logical clock, and increments the client's `version`. Only one submitted intake may exist per client; a second submission is rejected. When neither safety gate fires, intake submission advances the client from `PENDING_INTAKE` to `AWAITING_MATCH`.

The safety gate is the crux of intake. If the client reports an active crisis (`crisis_indicator` is true) or a `severity_score` of 8 or higher, the client does not advance — they remain in `PENDING_INTAKE`, and matching is blocked until a `ClinicalAdmin` clears the gate. Clearance is a distinct clinician action that takes a client who is in `PENDING_INTAKE` and for whom an intake exists, sets their status to `AWAITING_MATCH`, and increments the client's `version`. Should a proposal be attempted for a client whose intake severity is at least 8 or whose crisis indicator is true and who has not been cleared, the proposal is rejected with `ERR_INTAKE_NOT_CLEARED` (HTTP 409). A client returns to `ACTIVE` the moment their first match transitions from `PROPOSED` to `ACTIVE`, which is the natural end of the awaiting-match stage.

### 3.2. Building the Therapist Roster and License Coverage

A `ClinicalAdmin` onboards a `Therapist` by supplying a `full_name`, the therapist's `specialties` (a subset of the specialty vocabulary), and optionally a `max_active_caseload`, which is the largest number of simultaneously `ACTIVE` matches the therapist will carry and defaults to 30 (and must be at least 1). A new therapist begins in `ONBOARDING` with an `active_caseload` of zero; the `active_caseload` is the live count of this therapist's matches in `ACTIVE` and is constrained between zero and `max_active_caseload`.

Before a therapist can take clients they must be licensed. A `ClinicalAdmin` adds a `TherapistLicense` to a therapist by supplying the licensed `state_code` and the license's `expires_on` instant; the license records its owning `therapist_id`. A license is created `VALID` when its `expires_on` is strictly after the current clock and `EXPIRED` otherwise, and a license is considered valid only while the clock is before `expires_on` — which is exactly why advancing the clock recomputes every license's `status` (a license may also be `REVOKED`). Activation moves an onboarded therapist from `ONBOARDING` to `ACCEPTING`, but only when the therapist holds at least one license in `VALID` status; the activation increments the therapist's `version`. Deactivation moves a therapist from `ACCEPTING`, `FULL`, or `ONBOARDING` to the terminal `INACTIVE` state, permitted only when the therapist has zero matches in `ACTIVE`, and likewise increments their `version`.

The boundary between `ACCEPTING` and `FULL` is managed by the system as caseload moves. When a match becoming `ACTIVE` pushes a therapist's `active_caseload` up to equal `max_active_caseload`, an `ACCEPTING` therapist automatically flips to `FULL`. Conversely, when a match leaves `ACTIVE` and drops a `FULL` therapist's `active_caseload` below `max_active_caseload`, the therapist automatically flips back to `ACCEPTING`. These two transitions are mirror images and each fires whenever its caseload boundary is crossed.

### 3.3. Matching: Proposal, Acceptance, and the Fit Score

A `ClinicalAdmin` proposes a match between a client and a therapist by supplying the `client_id` and `therapist_id`. The proposal creates a `Match` in `PROPOSED` status and computes its `match_score`. The fit score is a weighted integer sum, computed with integer arithmetic and no rounding: it adds 10 points for each specialty the therapist shares with the client (the size of the intersection between the intake's `presenting_concerns` and the therapist's `specialties`), plus 25 points if the therapist holds a `VALID` license covering the client's `state_code` and 0 otherwise, plus 2 points for each unit of the intake's `severity_score`. A higher `match_score` denotes a better fit. Proposal is blocked by the intake safety gate described in §3.1, surfacing `ERR_INTAKE_NOT_CLEARED` for an uncleared at-risk client, and a therapist with no `VALID` license for the client's `state_code` cannot be matched, which raises `ERR_LICENSE_STATE_MISMATCH` (HTTP 409).

The client accepts a proposed match, which advances it from `PROPOSED` to `ACTIVE`. Acceptance is allowed only when the match is in `PROPOSED`, the client's `risk_flag` is not `ACUTE`, the therapist is in `ACCEPTING`, the therapist's `active_caseload` is still below their `max_active_caseload`, and the therapist holds a `VALID` license for the client's `state_code`. An attempt to accept while the client's risk posture is `ACUTE` is rejected with `ERR_CLIENT_RISK_BLOCKED` (HTTP 409), and a license-coverage failure here again raises `ERR_LICENSE_STATE_MISMATCH`. Acceptance fires a cascade: the match becomes `ACTIVE`, the therapist's `active_caseload` increases by one (which may bubble that therapist from `ACCEPTING` to `FULL`), a new `MessageThread` is created for the match in `OPEN`, and — if the client was still `AWAITING_MATCH` — the client is promoted to `ACTIVE`. The match's `version` increments.

### 3.4. The Care Relationship: Async Messaging and Switching Therapists

Each active match owns exactly one asynchronous `MessageThread`, identified by its `match_id`, that begins `OPEN` and tracks `unread_for_therapist`, a running count of client messages the therapist has not yet acknowledged. Either party to the match posts a `Message` to the thread by supplying its `body`, which must be non-empty and at most 4000 characters; the created message records its owning `thread_id` and a `sender_role` derived from the acting role (`CLIENT` or `THERAPIST`). When the sender is the client, the thread's `unread_for_therapist` increments. Messages may be posted only to a thread that is `OPEN`; posting to a `FROZEN` or `ARCHIVED` thread is rejected with `ERR_THREAD_NOT_OPEN` (HTTP 409).

Either the client or the therapist may request a switch on an `ACTIVE` match, which requires a `switch_reason` to be supplied and moves the match from `ACTIVE` to `SWITCH_REQUESTED` while freezing the match's thread from `OPEN` to `FROZEN`; the match's `version` increments. A `ClinicalAdmin` then performs the reassignment, which is only legal while the match is in `SWITCH_REQUESTED` and only when an eligible successor therapist can be found. The eligibility rule for a candidate therapist is precise: the candidate must be in `ACCEPTING`, must hold a `TherapistLicense` in `VALID` status whose `state_code` equals the client's `state_code`, must have an `active_caseload` strictly below their `max_active_caseload`, and must not be the same therapist as the one on the old match. Among all eligible candidates, the system selects the one with the highest `match_score`, breaking ties by the earliest therapist `created_at`. If no candidate qualifies, the reassignment is rejected with `ERR_NO_ELIGIBLE_THERAPIST` (HTTP 409).

A successful reassignment is a multi-record cascade. It creates a successor `Match` in `ACTIVE` for the selected new therapist — and that successor's own activation side effects fire, incrementing the new therapist's `active_caseload` (possibly bubbling them to `FULL`) and creating a fresh `OPEN` message thread. On the old match, the system sets `superseded_by_match_id` to the successor's `id`, moves the old match to the terminal `ENDED` state, decrements the old therapist's `active_caseload` by one (possibly bubbling them from `FULL` back to `ACCEPTING`), and archives the old match's thread from `FROZEN` to `ARCHIVED`. The old match's `version` increments. A match can also reach `ENDED` from `ACTIVE` directly under system control — when the client closes out or when a switch needs no successor — in which case the match becomes `ENDED`, the therapist's `active_caseload` decrements by one (again possibly bubbling `FULL` to `ACCEPTING`), and the match's thread is archived.

### 3.5. Live Sessions: Credits, Scheduling Conflicts, and Outcomes

Live sessions are the synchronous core of care, and each one consumes a session credit. Scheduling a live session against a match supplies the session's `starts_at`, its `ends_at` (which must be strictly after `starts_at`), and the `expected_match_version` described in §2.5. Scheduling is permitted only against an `ACTIVE` match. The created `LiveSession` records its owning `match_id`, begins in `SCHEDULED`, carries a `cancelled_within_window` flag that starts false, and links the credit it reserves through `session_credit_id`. The act of scheduling reserves exactly one `AVAILABLE`, non-expired `SessionCredit` for the client by moving that credit to `RESERVED` and writing the new session's `id` onto the credit's `live_session_id`, and it increments the match's `version`.

Three guards run when a session is scheduled, beyond the version check. First, the client's risk posture must not be `ACUTE` — scheduling for an `ACUTE` client is rejected with `ERR_CLIENT_RISK_BLOCKED`. Second, the new session must not overlap an existing non-terminal session on the same match: two sessions conflict when their half-open time intervals `[starts_at, ends_at)` intersect, though touching end-to-start (one session's end exactly equal to the next's start) is allowed; an overlap is rejected with `ERR_SESSION_OVERLAP` (HTTP 409). Third, the new session must respect a 15-minute buffer against every other non-terminal session belonging to the same therapist across all of that therapist's matches — two of the therapist's sessions must be at least 15 minutes apart, so a gap of less than a quarter hour between them is rejected with `ERR_THERAPIST_DOUBLE_BOOKED` (HTTP 409). Finally, scheduling requires at least one `AVAILABLE`, non-expired credit to reserve; if the client has none, the request is rejected with `ERR_NO_CREDIT` (HTTP 409).

A scheduled session resolves in one of three ways. The therapist completes it — legal only when the session is `SCHEDULED`, the clock has reached or passed `starts_at`, and the reserved credit is in `RESERVED` — which moves the session to `COMPLETED` and consumes the reserved credit (moving it to `CONSUMED`); the session's `version` increments. Either party may cancel a `SCHEDULED` session: cancellation moves it to `CANCELLED`, sets `cancelled_within_window` to true when the cancellation occurs less than 24 hours before `starts_at` and false otherwise, and resolves the reserved credit accordingly — a within-window cancellation forfeits the credit by moving it to `CONSUMED`, while a cancellation outside the window returns the credit to `AVAILABLE`. The therapist may mark a no-show, legal only when the session is `SCHEDULED` and the clock has reached or passed `ends_at`, which moves the session to `NO_SHOW` and forfeits the reserved credit by moving it to `CONSUMED`. Cancellation and no-show each increment the session's `version`.

### 3.6. Subscriptions, Billing Cycles, and Financial Aid

A subscription is created for a client by supplying the `client_id` and optionally a `base_weekly_fee_cents` (the list weekly fee before any discount, defaulting to 9900 and never negative) and a `weekly_credit_grant` (the number of live-session credits granted at the start of each cycle, defaulting to 1 and constrained between 0 and 4). A new `Subscription` begins in `TRIALING`. A client may hold only one non-terminal subscription at a time; an attempt to create a second is rejected with `ERR_DUPLICATE_SUBSCRIPTION` (HTTP 409).

Billing runs through charge cycles driven by a `BillingAdmin`. Charging the first paid cycle takes a `TRIALING` subscription to `ACTIVE`, while charging a renewal is a self-loop that keeps an `ACTIVE` subscription `ACTIVE`; a renewal is only due once the clock has reached or passed `current_period_start` plus 7 days, and a premature renewal is rejected with `ERR_CYCLE_NOT_DUE` (HTTP 409). Each charge creates a `BillingCycle` linked to the subscription via `subscription_id`, with a `period_start` and a `period_end` exactly 7 days later (the period is the half-open interval from inclusive `period_start` to exclusive `period_end`). The cycle's amounts are computed in a pinned order — the discount is applied first, then the wallet last. The `list_amount_cents` is the `base_weekly_fee_cents` reduced by the financial-aid discount and rounded half-up to whole cents, where the discount fraction is 0 for `NONE`, 0.20 for `TIER_1`, 0.40 for `TIER_2`, and 0.60 for `TIER_3` based on the client's current `financial_aid_tier`. The `wallet_applied_cents` is the smaller of the client's available `wallet_credit_cents` and the `list_amount_cents`, so wallet can zero out a cycle but the wallet balance never goes negative. The `charged_amount_cents` is the `list_amount_cents` minus the `wallet_applied_cents`. Once computed, the cycle is set `PAID`, `credits_granted` is set to the subscription's `weekly_credit_grant` and that many `SessionCredit` records are granted in `AVAILABLE` status with an `expires_on` of this period's `period_end` plus 28 days, the client's `wallet_credit_cents` is debited by the `wallet_applied_cents`, and the subscription's `current_period_start` is set on the first cycle or advanced by exactly 7 days on a renewal. The two charge variants — first cycle and renewal — use the identical amount formula; they differ only in whether `current_period_start` is initialized or stepped forward. Each granted credit also records the `billing_cycle_id` of the cycle that produced it.

Financial aid adjusts the discount. A client submits a `FinancialAidApplication` by supplying their `annual_income_cents` and `household_size` (the latter at least 1, the former never negative); the application begins `SUBMITTED`. A `BillingAdmin` either approves it — banding an `awarded_tier` and copying that tier onto the client's `financial_aid_tier` — or denies it, which moves the application to `DENIED` and leaves the client's `financial_aid_tier` unchanged. Both decisions increment the application's `version`. Banding works on an adjusted income: from the declared `annual_income_cents` the system subtracts a household allowance of $6,000 (600,000 cents) for each additional household member beyond the first — that is, the allowance multiplied by one less than `household_size` — and if the result would be negative it is treated as zero. The adjusted income is then compared against three ceilings using a strict less-than at every boundary, so an adjusted income exactly equal to a ceiling falls into the next-less-generous band: an adjusted income below $25,000 (2,500,000 cents) awards `TIER_3`; otherwise an adjusted income below $40,000 (4,000,000 cents) awards `TIER_2`; otherwise an adjusted income below $60,000 (6,000,000 cents) awards `TIER_1`; and any adjusted income of $60,000 or more awards `NONE`. Banding uses integer-cent subtraction only and performs no rounding.

### 3.7. Pausing, Resuming, and Cancelling a Subscription

A client may pause an `ACTIVE` subscription by supplying a `resume_on` instant together with the `expected_subscription_version` from §2.5. The resume instant must be strictly after the current clock and no later than 84 days after `current_period_start`; a resume instant beyond that 84-day horizon is rejected with `ERR_VALIDATION` (HTTP 422). Pausing moves the subscription to `PAUSED`, records `pause_resumes_on` as the supplied resume instant, computes a prorated refund credited to the wallet, and expires the current period's `AVAILABLE` credits by moving them to `EXPIRED`; the subscription's `version` increments. The refund is forward-looking and credited to `wallet_credit_cents` rather than charged back to a card. It starts from the `charged_amount_cents` of the latest `PAID` `BillingCycle` for the subscription and refunds the unused remainder of the current paid week at whole-day granularity. The number of elapsed days is the floor of the elapsed time from `current_period_start` to the current clock measured in whole days; the remaining days are 7 minus the elapsed days, floored at zero; and the refund is the paid amount multiplied by the remaining days divided by 7, rounded half-up to whole cents. As corollaries: a pause on the same day as the charge leaves all 7 days remaining and refunds the full paid amount, while a pause 7 or more days into the period leaves zero days remaining and refunds nothing.

A paused subscription returns to `ACTIVE` either when the client manually resumes it or when the logical clock reaches its `pause_resumes_on`. Resuming clears `pause_resumes_on` back to null and resets `current_period_start` to the current clock; the subscription's `version` increments. Cancellation is a scheduled affair. A client cancels an `ACTIVE` or `TRIALING` subscription, which moves it to `CANCEL_SCHEDULED` and sets `cancel_effective_on`: for an active subscription the effective instant is `current_period_start` plus 7 days (the end of the paid period), while for a trialing subscription the effective instant is the current clock. The cancellation increments the subscription's `version`. The final transition to `CANCELLED` happens either when the clock reaches `cancel_effective_on` or when a `BillingAdmin` finalizes it, and it is only legal once the clock has reached or passed `cancel_effective_on`; a premature finalize is rejected with `ERR_CANCEL_NOT_DUE` (HTTP 409). Reaching `CANCELLED` cascades into closing the client: a client in `ACTIVE` or `SUSPENDED` with no other non-terminal subscription moves to `CLOSED`, which in turn ends all of the client's `ACTIVE` matches (moving them to `ENDED`), expires all of the client's `AVAILABLE` or `RESERVED` credits (moving them to `EXPIRED`), and archives all of the client's `OPEN` or `FROZEN` message threads (moving them to `ARCHIVED`).

### 3.8. Crisis Escalation and the Safety Suspension Loop

A crisis escalation can be raised for a client by the client themselves, a therapist, or a clinical operator, by supplying a `severity` of either `ELEVATED` or `ACUTE`. Raising one creates a `CrisisEscalation` in `OPEN` status for the named client, records the `raised_by_role` of the raiser, and attaches the standardized safety-resource packet so that `safety_resources_sent` is set true on open. The escalation's severity sets the client's risk posture. An `ELEVATED` escalation sets the client's `risk_flag` to `ELEVATED`. An `ACUTE` escalation is more consequential: it sets the client's `risk_flag` to `ACUTE`, suspends the client by moving them from `ACTIVE` to `SUSPENDED`, and freezes the client's message threads from `OPEN` to `FROZEN`. While a client carries an `ACUTE` posture, match acceptance and new live-session scheduling are both blocked with `ERR_CLIENT_RISK_BLOCKED`.

A `ClinicalAdmin` works an escalation forward: acknowledging moves it from `OPEN` to `ACKNOWLEDGED`, and resolving moves it from `ACKNOWLEDGED` to `RESOLVED`; each step increments the escalation's `version`. Resolution carries the recovery cascade. If the escalation being resolved was `ACUTE` and the client has no other `OPEN` or `ACKNOWLEDGED` `ACUTE` escalation remaining, the client is restored from `SUSPENDED` to `ACTIVE`, their `risk_flag` is cleared to `NONE`, and their frozen threads are unfrozen from `FROZEN` back to `OPEN` (a thread unfreezes only when its owning match is itself still `ACTIVE`). If instead the resolved escalation was `ELEVATED` and the client has no other open escalations, the client's `risk_flag` is simply cleared to `NONE`. The suspended-to-active restoration is exactly the inverse of the acute suspension, and it is the only path back from a safety suspension.

### 3.9. Superbills and HSA Reimbursement

For reimbursement, a `BillingAdmin` drafts a `Superbill` for a client over a reporting window defined by a `period_start` and a `period_end` (the window is half-open: inclusive at the start, exclusive at the end). The draft begins in `DRAFT` and immediately computes its `session_count` and `reimbursable_amount_cents` over the window. Issuing the superbill recomputes those totals and moves it from `DRAFT` to `ISSUED`, but issuance is permitted only when at least one completed session falls in the window — a `session_count` of at least 1 — otherwise it cannot be issued. An issued superbill may later be voided by a `BillingAdmin`, moving it from `ISSUED` to the terminal `VOID`. Issue and void each increment the superbill's `version`.

The reimbursable computation is a chronological aggregation over the client's sessions. The system gathers every `LiveSession` whose match belongs to this client, whose status is `COMPLETED`, and whose `starts_at` falls within the half-open window (at or after `period_start` and strictly before `period_end`), ordering them deterministically by `starts_at` ascending and then by `created_at` ascending. The `session_count` is the number of such sessions. For each session in that order, the system finds the `PAID` `BillingCycle` whose own half-open period contains the session's `starts_at`, takes the per-session value as the floor of that cycle's `list_amount_cents` divided by its `credits_granted` (which is always at least 1), and adds that value to a running total. The final `reimbursable_amount_cents` is the exact sum of those per-session values with no post-sum rounding. Crucially, the per-session value is based on the cycle's `list_amount_cents` — the pre-wallet service value — and not on `charged_amount_cents`, because an HSA reimburses the value of the service rendered rather than the out-of-pocket cash a client paid after account credit was applied; this is the intended behavior even though it diverges from what the client actually paid when wallet credit offset a cycle.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify, transition, or otherwise act on an existing resource return `200 OK`. The clock-advance capability also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Register a client account (starts PENDING_INTAKE) | Client |
| GET | `/clients/{id}` | Fetch a client | Client, Therapist, ClinicalAdmin, BillingAdmin |
| GET | `/clients` | List clients (filterable by status) | ClinicalAdmin, BillingAdmin |
| POST | `/clients/{id}/intake` | Submit the intake questionnaire | Client |
| GET | `/clients/{id}/intake` | Fetch the client's intake questionnaire | Client, ClinicalAdmin |
| POST | `/clients/{id}/clear-intake` | Clear the severity/crisis intake gate | ClinicalAdmin |
| GET | `/clients/{id}/subscriptions` | List a client's subscriptions | Client, BillingAdmin |
| GET | `/clients/{id}/session-credits` | List a client's session credits | Client, ClinicalAdmin, BillingAdmin |
| GET | `/clients/{id}/crisis-escalations` | List a client's crisis escalations | Client, Therapist, ClinicalAdmin |
| GET | `/clients/{id}/financial-aid-applications` | List a client's financial-aid applications | Client, BillingAdmin |
| GET | `/clients/{id}/superbills` | List a client's superbills | Client, BillingAdmin |
| POST | `/clients/{id}/crisis-escalations` | Raise a crisis escalation for a client | Client, Therapist, ClinicalAdmin |
| POST | `/clients/{id}/financial-aid-applications` | Submit a financial-aid application | Client |
| POST | `/clients/{id}/superbills` | Draft a superbill for a window | BillingAdmin |
| POST | `/therapists` | Create a therapist (starts ONBOARDING) | ClinicalAdmin |
| GET | `/therapists/{id}` | Fetch a therapist | Client, Therapist, ClinicalAdmin, BillingAdmin |
| GET | `/therapists` | List therapists | ClinicalAdmin, BillingAdmin |
| POST | `/therapists/{id}/licenses` | Add a state license to a therapist | ClinicalAdmin |
| GET | `/therapists/{id}/licenses` | List a therapist's licenses | ClinicalAdmin, BillingAdmin |
| POST | `/therapists/{id}/activate` | Activate an onboarded therapist | ClinicalAdmin |
| POST | `/therapists/{id}/deactivate` | Deactivate a therapist with no ACTIVE matches | ClinicalAdmin |
| GET | `/therapists/{id}/matches` | List matches for a therapist | Therapist, ClinicalAdmin |
| POST | `/matches` | Propose a match (computes match_score) | ClinicalAdmin |
| GET | `/matches/{id}` | Fetch a match | Client, Therapist, ClinicalAdmin |
| GET | `/matches` | List matches | ClinicalAdmin |
| POST | `/matches/{id}/accept` | Client accepts a proposed match | Client |
| POST | `/matches/{id}/request-switch` | Request a therapist switch | Client, Therapist |
| POST | `/matches/{id}/reassign` | Reassign a switch-requested match | ClinicalAdmin |
| GET | `/matches/{id}/thread` | Fetch the match's message thread | Client, Therapist, ClinicalAdmin |
| GET | `/matches/{id}/live-sessions` | List a match's live sessions | Client, Therapist, ClinicalAdmin |
| POST | `/matches/{id}/live-sessions` | Schedule a live session (reserves a credit; OCC on match) | Client, Therapist |
| GET | `/live-sessions/{id}` | Fetch a live session | Client, Therapist, ClinicalAdmin |
| GET | `/live-sessions/{id}/session-credits` | List credits reserved/consumed by a session | Client, Therapist, ClinicalAdmin, BillingAdmin |
| POST | `/live-sessions/{id}/complete` | Mark a session COMPLETED | Therapist |
| POST | `/live-sessions/{id}/cancel` | Cancel a session | Client, Therapist |
| POST | `/live-sessions/{id}/no-show` | Mark a no-show after ends_at | Therapist |
| GET | `/threads/{id}` | Fetch a message thread | Client, Therapist, ClinicalAdmin |
| POST | `/threads/{id}/messages` | Post an async message to an OPEN thread | Client, Therapist |
| GET | `/threads/{id}/messages` | List messages in a thread | Client, Therapist, ClinicalAdmin |
| POST | `/subscriptions` | Create a subscription (starts TRIALING) | Client, BillingAdmin |
| GET | `/subscriptions/{id}` | Fetch a subscription | Client, BillingAdmin |
| POST | `/subscriptions/{id}/charge-cycle` | Charge a billing cycle | BillingAdmin |
| GET | `/subscriptions/{id}/billing-cycles` | List a subscription's billing cycles | Client, BillingAdmin |
| POST | `/subscriptions/{id}/pause` | Pause a subscription (refund to wallet; OCC on subscription) | Client |
| POST | `/subscriptions/{id}/resume` | Resume a paused subscription | Client |
| POST | `/subscriptions/{id}/cancel` | Schedule cancellation at end of paid period | Client |
| POST | `/subscriptions/{id}/finalize-cancel` | Finalize a scheduled cancellation once due | BillingAdmin |
| GET | `/billing-cycles/{id}` | Fetch a billing cycle | Client, BillingAdmin |
| GET | `/billing-cycles/{id}/session-credits` | List credits granted by a billing cycle | Client, BillingAdmin |
| GET | `/session-credits/{id}` | Fetch a session credit | Client, ClinicalAdmin, BillingAdmin |
| GET | `/session-credits/{id}/live-sessions` | List the session that reserved/consumed this credit | Client, Therapist, ClinicalAdmin, BillingAdmin |
| GET | `/crisis-escalations/{id}` | Fetch a crisis escalation | Client, Therapist, ClinicalAdmin |
| POST | `/crisis-escalations/{id}/acknowledge` | Acknowledge an escalation | ClinicalAdmin |
| POST | `/crisis-escalations/{id}/resolve` | Resolve an escalation (may restore client) | ClinicalAdmin |
| GET | `/financial-aid-applications/{id}` | Fetch a financial-aid application | Client, BillingAdmin |
| POST | `/financial-aid-applications/{id}/approve` | Approve aid (bands awarded_tier) | BillingAdmin |
| POST | `/financial-aid-applications/{id}/deny` | Deny aid | BillingAdmin |
| GET | `/superbills/{id}` | Fetch a superbill | Client, BillingAdmin |
| POST | `/superbills/{id}/issue` | Issue a drafted superbill | BillingAdmin |
| POST | `/superbills/{id}/void` | Void an issued superbill | BillingAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock to a UTC instant | ClinicalAdmin, BillingAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CLIENT_RISK_BLOCKED` | 409 Conflict |
| `ERR_INTAKE_NOT_CLEARED` | 409 Conflict |
| `ERR_LICENSE_STATE_MISMATCH` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SESSION_OVERLAP` | 409 Conflict |
| `ERR_THERAPIST_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_NO_CREDIT` | 409 Conflict |
| `ERR_THREAD_NOT_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_SUBSCRIPTION` | 409 Conflict |
| `ERR_CYCLE_NOT_DUE` | 409 Conflict |
| `ERR_NO_ELIGIBLE_THERAPIST` | 409 Conflict |
| `ERR_CANCEL_NOT_DUE` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
