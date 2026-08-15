# UI Claims Response API — Product Requirements Document

## 1. Introduction

When a former employee files for unemployment insurance, the burden of response falls on the employer — and the clock starts immediately. Each state sets its own response window, its own appeal window, and its own protest window for the quarterly charge statements that follow. Missing a deadline does not merely forfeit a single claim: late responses accumulate as strikes against the employer's compliance posture, and that posture feeds directly into the experience-rating formula that sets the employer's UI tax rate. Employers who delegate this work to a third-party administrator inherit a second risk — a TPA that files late still damages the employer's standing, and the employer needs the tooling to see it happening. The operational problem is therefore not one deadline but a lattice of interlocking deadlines, ledgers, and evidentiary gates, where a single late filing can cascade from a claim, to a compliance posture, to a tax rate.

This document specifies the UI Claims Response API, mounted under `/ui`, through which employers and their agents manage that entire lifecycle: claim notice intake and separation-reason coding, response drafting with evidentiary documentation assembly, state-by-state deadline tracking, hearing scheduling with witness preparation, determination and appeal handling with remand cycles, quarterly charge statement audit with erroneous-charge protest, experience-rating projection under both reserve-ratio and benefit-ratio formula families, and oversight of third-party administrator engagements. Seven operator roles share the workload under strict segregation of duties, and consistency is immediate — every filing, reversal, and reconciliation moves the affected ledgers at the moment it is recorded.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to specify their operational capacity. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes seven roles, spelled exactly as follows: `PlatformAdmin`, `ClaimsAnalyst`, `TpaAgent`, `AgencyLiaison`, `ChargeAuditor`, `RatingAnalyst`, and `TpaManager`. A `PlatformAdmin` is the platform operator who seeds state rules, employer accounts, and the logical clock. A `ClaimsAnalyst` is the employer-side analyst responsible for intake, separation coding, response drafting, evidence, hearings, and appeals. A `TpaAgent` is a third-party administrator filer acting under a TPA engagement's authority scope. An `AgencyLiaison` works the state-agency side: determinations, response acceptance, appeal decisions, charge statements, and protest adjudication. A `ChargeAuditor` is the employer-side auditor of charge statements and filer of charge protests. A `RatingAnalyst` is the employer-side experience-rating modeler. A `TpaManager` oversees TPA engagements: creating, suspending, reinstating, and terminating them.

For every one of these seven roles — `PlatformAdmin`, `ClaimsAnalyst`, `TpaAgent`, `AgencyLiaison`, `ChargeAuditor`, `RatingAnalyst`, and `TpaManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, the drafting operator's identifier is recorded internally on each claim response so the segregation-of-duties check can compare it against the identifier that later accepts or rejects that response), but the server never compares `X-User-ID` to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400); an out-of-range value is not rejected but clamped — `limit` into the inclusive range from 1 to 100, and a negative `offset` up to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; resources sharing a creation timestamp are ordered by creation sequence (the order in which the server created them).

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in this API — employer accounts, TPA engagements, state rules, separations, claims, responses, evidence documents, determinations, appeals, hearings, witnesses, charge statements, charge line items, charge protests, and experience-rating models — carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-08-01T09:15:00.123Z`), set when the resource is first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- **`version` (integer):** A system-managed integer that increments by one with every modification to the resource. Recomputations of derived fields — a claim's adjudication posture, a statement's total, an employer's posture or rate — are mutations and therefore refresh `updated_at` and increment `version` on the owning resource.

Every other datetime-valued field carried on a resource — business timestamps such as `notice_received_at`, `response_due_at`, and `filed_at` — is rendered as an ISO 8601 UTC timestamp pinned to whole seconds, with no fractional component (e.g., `2026-08-13T17:00:00Z`); on resources, the three-fractional-digit form applies only to the system-managed `created_at` and `updated_at` fields above.

### 2.5. The Logical Clock and Filing Time

The server maintains a logical clock rather than reading wall-clock time. At startup, before any operator has set it, the clock reads exactly `2026-08-01T00:00:00Z` and never falls back to wall-clock time. A `PlatformAdmin` may advance the clock through a test-driving capability that accepts a `to_iso8601` timestamp — any parseable ISO 8601 timestamp is accepted, earlier or later than the current reading, and the clock is set to exactly that instant — and reports the supplied value back as `current_utc`. Every deadline computation and every `filed_at` stamp in the system reads this logical clock, so on-time and late determinations are always made against the same clock the operator can control. Every other server-generated timestamp — the envelope's `api_request_timestamp` and every resource's `created_at` and `updated_at` — reads this same logical clock as well.

### 2.6. Deadline Arithmetic: Counting Days, Holidays, and the End-of-Day Pin

Three deadlines govern the employer's obligations, and all three share one convention: the result is a calendar date pinned to 17:00:00 UTC — the end-of-day pin — so a filing made at or before 17:00:00 UTC on the due date is on time. The response deadline additionally depends on how the adjudicating state counts days, a choice recorded on the state's rule as `window_basis`. Under the `CALENDAR` basis, every day counts: the due date is the notice date plus the state's `response_window_days` calendar days. Under the `BUSINESS` basis, weekends and holidays never count, so identical inputs yield a later due date than the calendar basis. The federal holiday calendar used by both bases — and by the weekend-shift rule below — is a fixed list of eleven 2026 dates: 2026-01-01, 2026-01-19, 2026-02-16, 2026-05-25, 2026-06-19, 2026-07-03, 2026-09-07, 2026-10-12, 2026-11-11, 2026-11-26, and 2026-12-25.

After the basis-specific computation, every deadline is subject to the state's `weekend_shift` rule. When `weekend_shift` is `NEXT_BUSINESS_DAY`, a due date landing on a Saturday, Sunday, or federal holiday advances one day at a time until it lands on a business day; when `weekend_shift` is `NONE`, the computed date stands as-is. All deadline dates are computed in the state's timezone, which is assumed to be UTC. Finally, the boundary between timely and late is always inclusive: a filing whose `filed_at` is exactly equal to the computed deadline is `ON_TIME`, not `LATE`. Timeliness comparisons are made at second granularity on timestamps.

### 2.7. Money, Basis Points, and Scores: Precision Discipline

All monetary values are stored and returned as integer cents in fields whose names end in `_cents` — no floating-point money appears anywhere in the API. Tax rates are expressed as integer basis points. Scores (`completeness_score`, `evidence_strength`) are integer points requiring no rounding. The compliance-posture arithmetic operates at half-strike granularity, because each denied protest contributes one half of a strike.

The experience-rating projection applies a pinned rounding order: the ratio is carried as an exact rational number and is never rounded before the tier lookup; the tiered rate is an integer number of basis points; and the projected liability is computed from that integer rate and then rounded down to a whole cent. Rounding the ratio before tiering is forbidden, because it would change which tier a boundary ratio selects.

### 2.8. Validation Pipeline and Nested Resource Retrieval

Every request passes through a single ordered validation pipeline, and the order matters because it determines which error surfaces when several checks would fail. The tiers, evaluated in strict order, are:

1. **Header presence and role recognition** — missing or invalid `X-User-ID` / `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role permission** — the role is not authorized for this endpoint: `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Body well-formedness** — for endpoints with a body, required fields must be present, types must match, and enum values must lie in their declared domains; violations yield `ERR_INVALID_REQUEST` (HTTP 400). This schema check runs after authentication but before any path-existence lookup.
4. **Path existence, left to right** — when a path contains multiple resource identifiers, each is validated in left-to-right order and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the *first* identifier that does not exist; later identifiers are not examined.
5. **Cross-parent reference integrity** — on nested creates and filings, foreign keys in the body must resolve and must belong to the path-scoped parent: a response body's `claim_id` must equal the claim in the path, and a claim's separation must belong to the same employer as the claim itself. A reference that resolves but belongs to a different parent yields `ERR_CROSS_PARENT_REFERENCE` (HTTP 422).
6. **State preconditions** — the target entity must be in a state that permits the requested transition; generic failures yield `ERR_INVALID_STATE` (HTTP 409), and the workflow-specific state errors catalogued in §5 are raised at this tier.
7. **Filing windows** — filings are checked against their computed deadlines, and structurally invalid intervals (a hearing whose end is not after its start) are rejected with `ERR_WINDOW_VIOLATION` (HTTP 422); filing lateness itself is expressed through the `LATE` and dismissal branches described in §3, not rejected here.
8. **Temporal overlap** — referee double-booking and witness availability containment, the category labelled `ERR_TEMPORAL_OVERLAP`, surface as the specific catalog errors `ERR_REFEREE_DOUBLE_BOOKED` and `ERR_WITNESS_UNAVAILABLE` (HTTP 409).
9. **TPA window exclusivity** — an engagement window that intersects a sibling engagement's window yields `ERR_TPA_WINDOW_OVERLAP` (HTTP 409).
10. **TPA authority and segregation of duties** — the engagement must be active, in-window, and scoped for the filing, and the operator who drafted a response may not be the one to accept or reject it; this category, `ERR_AUTHORITY_VIOLATION` (HTTP 403), surfaces concretely as `ERR_TPA_SCOPE_VIOLATION`, `ERR_TPA_NOT_ACTIVE`, or — for a segregation-of-duties rejection — `ERR_AUTHORITY_VIOLATION` itself.
11. **Evidence sufficiency gates** — the category `ERR_INSUFFICIENT_EVIDENCE` (HTTP 422) surfaces concretely as `ERR_RESPONSE_INCOMPLETE`, `ERR_CODING_EVIDENCE_MISSING`, `ERR_CONTINUANCE_LIMIT`, or `ERR_PROTEST_EVIDENCE_WEAK`.
12. **Uniqueness** — duplicate active records (a repeated claim number within a state, a second open protest on one line, a second finalized official rating model) yield `ERR_DUPLICATE_ACTIVE_RECORD` (HTTP 409).
13. **Aggregate fiscal caps** — charge postings that would exceed a claim's maximum benefit or violate fiscal domain rules yield `ERR_MAX_BENEFIT_EXCEEDED` or `ERR_FISCAL_CAP_EXCEEDED` (HTTP 422).
14. **Optimistic concurrency** — version checks run last, so that business errors always surface before a stale-version rejection with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Optimistic Concurrency Control

Three write operations require the client to prove it has observed the current state of a parent aggregate before writing. Each takes a non-optional expected-version field; if the value does not match the parent entity's current `version` — because another writer has advanced that version since the client last read the parent — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The version check is evaluated after every business rule (see §2.8), so a request that fails both a business rule and the version check reports the business error.

- **Submitting a claim response** requires `expected_claim_version` carrying the client's last observed `version` of the parent claim. A drafter who loaded the claim before a colleague attached new evidence — an attachment that itself bumps the claim's version — holds a stale version and must re-read the claim before filing.
- **Filing a charge protest** requires `expected_statement_version` carrying the client's last observed `version` of the parent charge statement. A sibling protest that reversed a line recomputes the statement's totals and advances its version; protest decisions are always made against current statement totals.
- **Finalizing an experience-rating model** requires `expected_employer_version` carrying the client's last observed `version` of the parent employer account. Finalization supersedes the prior finalized official model for the same employer and year, so the server refuses to supersede on inputs the client has not observed.

No endpoint other than these three takes a version field.

### 2.10. The Employer's Standing: Reserve, Protest Credits, and Compliance Strikes

Three counters on the employer account summarize its financial and compliance standing, and workflows across §3 move them. The `reserve_balance_cents` ledger holds cumulative contributions minus cumulative benefits charged; it is debited when a charge line posts and credited exactly once when a charge is reversed or waived — reconciliation never re-credits it. The `protest_credits_cents` counter accumulates the amounts won through sustained charge protests, accruing at statement reconciliation time only; a waived line is agency goodwill and accrues nothing. The `late_response_strikes` counter records how many claims missed their response deadline.

These inputs combine into the employer's `compliance_posture` — `CLEAR`, `WATCH`, or `SANCTIONED`. The effective strike count is the employer's `late_response_strikes` plus one half strike for every denied charge protest on the employer's statements. An effective count of at least four yields `SANCTIONED`; an effective count of at least two but fewer than four yields `WATCH`; anything lower yields `CLEAR`. Both boundaries are inclusive: exactly 2.0 effective strikes is `WATCH`, and exactly 4.0 is `SANCTIONED`. The posture is recomputed whenever a late strike lands, whenever a protest is denied, and whenever a claim closes. Posture is not merely cosmetic — §3.7 shows it feeding a surcharge directly into the employer's tax rate.

## 3. Business Logic & Workflows

### 3.1. Employers, State Rules, and Third-Party Administrator Oversight

Everything in the system hangs off the employer account. A `PlatformAdmin` creates one by supplying its `legal_name`, its `fein` (a 9-digit string, globally unique across accounts — a duplicate `fein` is rejected with `ERR_DUPLICATE_ACTIVE_RECORD`), its `merit_rating_method` — either `RESERVE_RATIO` or `BENEFIT_RATIO`, selecting the experience-rating formula family its state uses — and its `taxable_payroll_cents`, the trailing taxable payroll base used in rating denominators. The account may optionally seed `reserve_balance_cents`, which starts at zero when omitted. A new account begins with `compliance_posture` `CLEAR`, zero `late_response_strikes`, zero `protest_credits_cents`, and a `current_tax_rate_bps` computed at creation — 270 basis points until the experience-rating projection of §3.7 recomputes it.

Deadline policy lives on per-state rule records. A `PlatformAdmin` registers each state's `state_code` (a unique two-letter USPS code — registering a second rule for the same `state_code` is rejected with `ERR_DUPLICATE_ACTIVE_RECORD`), its `response_window_days` with a `window_basis` of `CALENDAR` or `BUSINESS`, its `appeal_window_days`, its `protest_window_days`, and its `weekend_shift` of `NEXT_BUSINESS_DAY` or `NONE`. Claims and charge statements reference the adjudicating or issuing state by its code — looked up by `state_code`, never by the rule's `id`; a body naming an unregistered `state_code` is rejected with `ERR_NOT_FOUND` (HTTP 404).

An employer's work may be delegated. A `TpaManager` engages a third-party administrator by naming the represented `employer_id`, the firm's `tpa_name`, an `authority_scope` of `RESPONSE_ONLY`, `RESPONSE_AND_HEARING`, or `FULL`, and an inclusive engagement window from `effective_from` to `effective_to`. A new engagement's `oversight_status` starts `ACTIVE` with a `breach_count` of zero. Engagement windows are exclusive per employer: creating an engagement whose closed interval — both endpoints included — intersects the interval of any existing non-`TERMINATED` engagement for the same employer is rejected with `ERR_TPA_WINDOW_OVERLAP`, and two windows that merely touch at a boundary timestamp do intersect.

Scope is enforced at filing time. When a `TpaAgent` drafts a response naming a `filed_by_tpa_id`, the named engagement must cover the claim's employer — an engagement belonging to a different employer yields `ERR_CROSS_PARENT_REFERENCE` — and it must be `ACTIVE` or `REINSTATED` (a suspended or terminated engagement yields `ERR_TPA_NOT_ACTIVE`) with an `authority_scope` that authorizes response filings — `RESPONSE_ONLY`, `RESPONSE_AND_HEARING`, and `FULL` each do — or the draft is rejected with `ERR_TPA_SCOPE_VIOLATION`; the engagement's effective window is not consulted at draft time. When a `TpaAgent` drafts without naming an engagement, some `ACTIVE` or `REINSTATED` engagement with response-filing scope must cover the claim's employer, or the draft is rejected with `ERR_TPA_SCOPE_VIOLATION`. When a TPA-filed response is submitted, the engagement must still be `ACTIVE` or `REINSTATED` and inside its effective window at the moment of filing; a suspended or terminated engagement, or one outside its window, yields `ERR_TPA_NOT_ACTIVE`. While an engagement is `SUSPENDED`, every `TpaAgent` filing under it is rejected with `ERR_TPA_NOT_ACTIVE`.

Breaches are counted and punished automatically. Each late response filed under an engagement adds one to its `breach_count`, and when the count reaches three the engagement suspends itself — `ACTIVE` becomes `SUSPENDED`, and a re-offending `REINSTATED` engagement becomes `SUSPENDED` again. A `TpaManager` may also suspend an engagement directly — suspension is possible from `ACTIVE` or `REINSTATED`, and any other status yields `ERR_INVALID_STATE`. Reinstatement requires the engagement to be `SUSPENDED` (otherwise `ERR_TPA_NOT_SUSPENDED`) and a `remediation_note` of at least 20 characters (otherwise `ERR_REMEDIATION_NOTE_SHORT`); a reinstated engagement's `oversight_status` becomes `REINSTATED` and its `breach_count` resets to one, not zero — prior history is retained. Termination is possible only from `ACTIVE` or `SUSPENDED` — any other status yields `ERR_INVALID_STATE` — and is blocked while any claim sits in `RESPONSE_IN_PROGRESS` with a `DRAFT` response bound to that engagement via `filed_by_tpa_id` (`ERR_TPA_HAS_OPEN_WORK`); otherwise the engagement becomes `TERMINATED`, its terminal state. The roster of responses filed under an engagement remains retrievable for oversight.

### 3.2. Separations and Reason-Coding Confidence

Before a claim can be answered, the underlying separation must be on record. A `ClaimsAnalyst` records a `ClaimantSeparation` with the separating `employer_id`, the `claimant_name`, the claimant's `ssn_last4` (a 4-digit string), the `last_day_worked`, and the `separation_reason`: one of `VOLUNTARY_QUIT`, `DISCHARGE_MISCONDUCT`, `DISCHARGE_NON_MISCONDUCT`, `LAYOFF`, or `LEAVE_OF_ABSENCE`. The record's `reason_coding_confidence` begins `UNREVIEWED`.

Coding confirmation is evidence-gated for misconduct. A `ClaimsAnalyst` may confirm the coding, setting confidence to `CONFIRMED` whatever its current value — `UNREVIEWED`, `CONFIRMED`, or `DISPUTED`; but when the reason is `DISCHARGE_MISCONDUCT`, at least one evidence document in the `WRITTEN_WARNING`, `SIGNED_POLICY`, or `FINAL_INCIDENT_REPORT` category must already be attached to some claim referencing that separation, or the confirmation is rejected with `ERR_CODING_EVIDENCE_MISSING`.

Confidence is a living axis, not a one-way ratchet — `CONFIRMED` and `DISPUTED` may cycle as evidence accumulates. Two events challenge the employer's coding and push confidence to `DISPUTED`: the state agency rejecting a response as insufficient, and the employer losing the timely-protest presumption by filing late. One event vindicates it: a determination that denies the claim moves a `DISPUTED` coding back to `CONFIRMED`. Section 3.6 shows this confidence feeding the strength score of every charge protest on the claim.

### 3.3. Claim Notice Intake and the Response Deadline

A claim enters the system when a `ClaimsAnalyst` or an `AgencyLiaison` records the notice: the charged `employer_id`, the `separation_id` of the separation the claim references, the adjudicating `state_code`, the state-issued `state_claim_number` (unique within its state — a duplicate is rejected with `ERR_DUPLICATE_ACTIVE_RECORD`), the `notice_received_at` timestamp, the `benefit_year_begin` anchoring the charge-allocation window, the state-computed `weekly_benefit_amount_cents`, and the `max_benefit_cents` payable on the claim. The claim's `status` opens at `NOTICE_RECEIVED`, its `charged_amount_cents` at zero, and its `response_channel` stays null until a response is actually submitted, when it becomes `SELF` or `TPA`.

Intake computes the response deadline immediately. The base is the date part of `notice_received_at`, read in the state's timezone (assumed UTC). Under a `CALENDAR` basis the due date is the base plus the state's `response_window_days` days, every day counting. Under a `BUSINESS` basis the system starts at the base date with a counter equal to `response_window_days` and walks forward one day at a time: each day falling Monday through Friday that is not a federal holiday decrements the counter by one, while Saturdays, Sundays, and federal holidays never decrement it, and the due date is the day the counter reaches zero. Either way, the state's `weekend_shift` then applies per §2.6, and the result is pinned to 17:00:00 UTC as the claim's `response_due_at`.

Deadline pressure is surfaced on the claim itself. While a claim sits in `NOTICE_RECEIVED` or `RESPONSE_IN_PROGRESS` and no more than 48 hours remain before `response_due_at` — a deadline already past satisfies this — its `adjudication_posture` reads `EXPEDITED`; otherwise it reads `STANDARD`. The posture is computed at intake and recomputed whenever a response draft is created, whenever a response on the claim is submitted, and whenever the claim is withdrawn or closed.

Claims can be listed with optional filters — `employer_id`, `state_code`, `status`, and `separation_id` — and each claim exposes its responses, evidence, determinations, hearings, and charge line items for reverse reachability.

Withdrawal ends a claim early. An `AgencyLiaison` may withdraw a claim only while it is in `NOTICE_RECEIVED` or `RESPONSE_IN_PROGRESS` (otherwise `ERR_CLAIM_NOT_WITHDRAWABLE`); the claim becomes `WITHDRAWN`, a terminal state, and every `DRAFT` response on it is superseded.

### 3.4. Drafting, Documenting, and Filing the Response

A response begins as a draft created by a `ClaimsAnalyst` or a scoped `TpaAgent`. The drafting payload carries the `response_type` — `PROTEST`, `NO_PROTEST`, or `INFORMATION_ONLY` — the employer-asserted `separation_reason_code` (which must equal the separation's recorded reason, otherwise `ERR_INVALID_REQUEST`), a free-text `narrative`, and two optional references: `filed_by_tpa_id` naming the engagement under which a TPA files, and `amendment_of` naming an earlier response this one amends. The draft references the claim it answers via `claim_id`.

Drafting is only possible while the claim is in `NOTICE_RECEIVED`, `RESPONSE_IN_PROGRESS`, or `RESPONSE_SUBMITTED` — anything else is rejected with `ERR_CLAIM_NOT_RESPONSIVE` — and from `RESPONSE_SUBMITTED` only an amendment (one with `amendment_of` set) may be drafted. The very first draft moves the claim from `NOTICE_RECEIVED` to `RESPONSE_IN_PROGRESS`; drafts created while the claim is already in `RESPONSE_IN_PROGRESS` or `RESPONSE_SUBMITTED` add the `DRAFT` or amendment row and increment the claim's `version` by one without changing the claim's `status`. Every draft creation also recomputes the claim's `adjudication_posture` and increments `UiClaim.version` by one. The response itself starts in `DRAFT`. Drafting an amendment immediately supersedes the response it names in `amendment_of` when that response is still `DRAFT`.

Evidence accumulates against the claim while drafts mature. A `ClaimsAnalyst` or `TpaAgent` attaches an `EvidenceDocument` with its `doc_category` — `WRITTEN_WARNING`, `SIGNED_POLICY`, `FINAL_INCIDENT_REPORT`, `ATTENDANCE_RECORD`, `PERFORMANCE_REVIEW`, `RESIGNATION_LETTER`, or `OTHER` — the real-world `doc_date`, an `authenticated` flag recording whether the document carries a signature or attestation, and an optional `response_id`; the document records the claim it supports via `claim_id`. Each attachment and each removal (removal restricted to `ClaimsAnalyst`, returning 204 with no data) recomputes the documentation assembly score on the referenced response — or, when `response_id` is omitted, on the claim's latest `DRAFT` response — and increments the claim's `version` by one, because the claim's evidentiary posture changed and submission's concurrency check observes it.

The assembly score rewards the best evidence in each category exactly once, and it is computed over every evidence document attached to the claim, whatever response (if any) each document references. Each document's contribution is its category's base weight — 25 for `WRITTEN_WARNING`, 20 for `SIGNED_POLICY`, 30 for `FINAL_INCIDENT_REPORT`, 15 for `ATTENDANCE_RECORD`, 10 for `PERFORMANCE_REVIEW`, 25 for `RESIGNATION_LETTER`, and 5 for `OTHER` — plus 10 points when the document is authenticated, minus 5 points when its `doc_date` is later than the claim's `notice_received_at`, a post-hoc discount. Within each category only the single best-scoring document contributes. The raw score is the sum of those per-category bests across the categories present, and the response's `completeness_score` is that raw sum capped at 100. Each document's own `weight_points` records its individual contribution value.

Submission is the point of no return for the draft. The response must still be `DRAFT` (otherwise `ERR_RESPONSE_NOT_DRAFT`), its `completeness_score` — recomputed at submission time over the claim's then-current evidence — must be at least 40 (otherwise `ERR_RESPONSE_INCOMPLETE`), and a TPA-filed response must be backed by an engagement that is `ACTIVE` or `REINSTATED` and inside its effective window at filing time (otherwise `ERR_TPA_NOT_ACTIVE`). The request must carry `expected_claim_version` matching the claim's current `version`, as §2.9 requires. On submission the server stamps `filed_at` from the logical clock and computes `timeliness`: `ON_TIME` when `filed_at` is at or before the claim's `response_due_at` — equality included — and `LATE` otherwise. The response moves from `DRAFT` to `SUBMITTED`, the claim's `response_channel` is set to `TPA` when `filed_by_tpa_id` is present and `SELF` otherwise, and the claim's `version` increments by one.

Where the claim lands depends on timeliness. An on-time submission advances the claim from `RESPONSE_IN_PROGRESS` to `RESPONSE_SUBMITTED`. A late submission instead branches the claim to `LATE_RESPONSE`, and the lateness cascades: the employer's `late_response_strikes` increases by one and its `compliance_posture` is recomputed per §2.10, and if the filing was TPA-made the engagement's `breach_count` increases by one with automatic suspension at three breaches per §3.1.

The state agency then acknowledges receipt — simulated through a `PlatformAdmin`-only test-driving capability identified by `claim_id`; a claim in any status other than `RESPONSE_SUBMITTED` or `LATE_RESPONSE` is rejected with `ERR_INVALID_STATE`. From `RESPONSE_SUBMITTED` the claim simply moves to `UNDER_ADJUDICATION`. From `LATE_RESPONSE` the same move additionally flags the late response on the adjudication record — surfaced as a `late_flagged` boolean set to true on the claim — and the employer loses the timely-protest presumption on reason coding: a separation whose `reason_coding_confidence` was `CONFIRMED` becomes `DISPUTED`.

Acceptance and rejection belong to the `AgencyLiaison`, and only a `SUBMITTED` response can receive either (otherwise `ERR_RESPONSE_NOT_SUBMITTED`). Acceptance moves the response to `ACCEPTED` and supersedes every other `SUBMITTED` or `DRAFT` response on the same claim — including the earlier response an accepted amendment named in `amendment_of`, which moves from `SUBMITTED` to `SUPERSEDED`. Rejection moves the response to `REJECTED_INSUFFICIENT` and challenges the employer's coding by setting the separation's confidence to `DISPUTED`. Segregation of duties applies at both gates: the operator whose `X-User-ID` drafted a response cannot be the operator who accepts or rejects it, and the server enforces this by comparing the caller's identifier against the drafter's identifier recorded at draft time, rejecting a violation with `ERR_AUTHORITY_VIOLATION` (HTTP 403). Responses can also die quietly: a draft is superseded when a newer response is accepted, when the claim is withdrawn, or when an amendment naming it is drafted. `ACCEPTED`, `REJECTED_INSUFFICIENT`, and `SUPERSEDED` are terminal. A response's own amendment chain — the responses whose `amendment_of` points back to it — and its attached evidence remain retrievable.

### 3.5. Determinations, Appeals, Hearings, and Witnesses

Adjudication concludes its first pass when an `AgencyLiaison` records the agency's determination on a claim that is `UNDER_ADJUDICATION` (otherwise `ERR_CLAIM_NOT_UNDER_ADJUDICATION`). The record carries the `claim_id` of the adjudicated claim, an `outcome` of `ALLOWED`, `DENIED`, or `ALLOWED_NO_CHARGE` (allowed, but the employer's account is not charged), the `mailed_at` date, and an optional `disqualification_weeks` count (default zero) for the weeks of disqualification imposed when a claim is allowed with penalty. The determination opens in `ISSUED` status, and its `appeal_due_at` is computed as the date part of `mailed_at` plus the state's `appeal_window_days` calendar days — the appeal window always counts calendar days regardless of `window_basis` — with `weekend_shift` applied and the result pinned to 17:00:00 UTC. Recording the determination moves the claim to `DETERMINED`. An `ALLOWED` outcome makes the claim chargeable: subsequent charge-line postings debit the claim's `charged_amount_cents` and the employer's reserve as §3.6 describes — though as §3.6 pins, posting enforces no determination-outcome gate. A `DENIED` outcome recorded while the separation's coding confidence is `DISPUTED` vindicates the employer, returning confidence to `CONFIRMED`.

Either party may appeal while the determination is `ISSUED` (otherwise `ERR_DETERMINATION_NOT_APPEALABLE`). The filing — by a `ClaimsAnalyst` for the employer or an `AgencyLiaison` recording a claimant appeal (either authorized role may file either appellant) — names the `determination_id`, an `appellant` of `EMPLOYER` or `CLAIMANT`, and free-text `grounds`. The server stamps `filed_at` and computes `timeliness`, with the inclusive boundary: a filing exactly at `appeal_due_at` is `ON_TIME`. A timely filing creates the appeal in `FILED` with `round_number` one, flips the determination to `APPEALED_BY_EMPLOYER` or `APPEALED_BY_CLAIMANT` according to the appellant, and moves the claim from `DETERMINED` to `HEARING_PENDING`. A late filing is detected at filing time: the appeal goes straight to `DISMISSED_UNTIMELY`, the determination becomes `FINAL`, and the claim stays `DETERMINED`.

Scheduling a hearing dockets the appeal. A `ClaimsAnalyst` schedules the first hearing on a `FILED` appeal (otherwise `ERR_APPEAL_NOT_DOCKETABLE`) by supplying the `claim_id` (denormalized onto the hearing for scheduling queries), the `scheduled_start` and `scheduled_end` (the end must be strictly after the start, otherwise `ERR_WINDOW_VIOLATION`), the `referee_id`, and the `location`. The hearing references its appeal via `appeal_id`, opens in `SCHEDULED` with a `continuance_count` of zero, and the appeal moves from `FILED` to `DOCKETED`. Referees are protected by a buffer rule: the same referee may hold no other `SCHEDULED` or `HELD` hearing whose interval, expanded by thirty minutes on both sides, intersects the new one — intersection is closed on both ends, so intervals that merely touch also conflict — a conflict is rejected with `ERR_REFEREE_DOUBLE_BOOKED`. This buffer check runs at scheduling, again at every witness addition, and again at every continuance.

Witnesses drive preparation. A `ClaimsAnalyst` adds each witness with a `full_name`, a `witness_role` of `DIRECT_SUPERVISOR`, `HR_CUSTODIAN`, `POLICY_AUTHOR`, `CLAIMANT`, or `OTHER`, and an availability window from `availability_start` to `availability_end`; the witness records its hearing via `hearing_id`. Witnesses may be added while the hearing is `SCHEDULED`, `PREP_IN_PROGRESS`, or `READY`; adding to a `HELD` or `CLOSED` hearing is rejected with `ERR_INVALID_STATE`. The availability window must contain the entire hearing interval — `availability_start` at or before `scheduled_start` and `availability_end` at or after `scheduled_end` — or the addition is rejected with `ERR_WITNESS_UNAVAILABLE`. Adding the first witness moves the hearing from `SCHEDULED` to `PREP_IN_PROGRESS`, and adding a witness to a `READY` hearing — the new witness being `UNPREPARED` — returns it to `PREP_IN_PROGRESS`. Each witness's `prep_status` begins `UNPREPARED`, and every preparation step advances it one rung: `UNPREPARED` to `BRIEFED`, `BRIEFED` to `EXHIBITS_REVIEWED`, `EXHIBITS_REVIEWED` to `READY`; advancing a witness already `READY` is rejected with `ERR_INVALID_STATE`. When every witness has reached `READY` and at least one witness exists, the hearing automatically becomes `READY`.

Continuances are limited and re-validated. A `ClaimsAnalyst` may reschedule a hearing while it is `SCHEDULED`, `PREP_IN_PROGRESS`, or `READY` (any other status yields `ERR_INVALID_STATE`) and only while its `continuance_count` is below three (a third request beyond that is rejected with `ERR_CONTINUANCE_LIMIT`); the proposed new interval must pass both the referee buffer-overlap check and the witness availability containment check again. A granted continuance increments `continuance_count` by one, replaces `scheduled_start` and `scheduled_end`, and passes the hearing through `CONTINUED` straight back into `SCHEDULED` — an immediate re-entry, not a resting state; if every witness is already `READY` at that point, the hearing promotes to `READY` again immediately.

Only a prepared hearing can be held. An `AgencyLiaison` marks the hearing held only when it is `READY` — which, by the rule above, means every witness is `READY` — otherwise `ERR_HEARING_NOT_READY`. The hearing moves from `READY` to `HELD`, and the appeal moves from `DOCKETED` to `HEARD`. `HELD` and `CLOSED` are the hearing's terminal states.

The appeal decision, recorded by an `AgencyLiaison` with a `decision`, requires the appeal to be `HEARD` (otherwise `ERR_APPEAL_NOT_HEARD`) and has three symmetric branches:

- **Affirm.** The appeal becomes `DECIDED_AFFIRMED`, the determination becomes `FINAL`, and the claim returns from `HEARING_PENDING` to `DETERMINED`.
- **Reverse.** The appeal becomes `DECIDED_REVERSED` and the determination becomes `REVERSED`. When the reversed determination's outcome was `ALLOWED`, every charge line on that claim still in `PENDING` or `SUSTAINED` automatically transitions to `REVERSED`; each such reversal decrements its statement's `total_charged_cents` and the claim's `charged_amount_cents` by the line's amount, and the employer's `reserve_balance_cents` is credited by the sum of all auto-reversed amounts — exactly one credit per reversed line, restoring the pre-charge ledger. All experience-rating models for the employer move to `SUPERSEDED`, because their inputs have been invalidated. The reverse branch does not move the claim: it remains `HEARING_PENDING`.
- **Remand.** The appeal becomes `REMANDED`, the determination becomes `REVERSED`, and the claim reopens from `HEARING_PENDING` to `UNDER_ADJUDICATION`, where a fresh determination restarts the loop. A re-appeal filed in the new cycle carries a `round_number` one greater than the highest `round_number` among the claim's `REMANDED` appeals (one when none exists).

Withdrawal is the employer's exit ramp. A `ClaimsAnalyst` may withdraw an appeal while it is `FILED` or `DOCKETED` (otherwise `ERR_APPEAL_NOT_WITHDRAWABLE`): the appeal becomes `WITHDRAWN`, the determination becomes `FINAL`, the claim returns from `HEARING_PENDING` to `DETERMINED`, and any hearing for that appeal still in `SCHEDULED`, `PREP_IN_PROGRESS`, or `READY` is closed; witness rows remain for audit with their `prep_status` frozen.

Closure is the claim's last act. A `ClaimsAnalyst` may close a claim only when it is `DETERMINED` (otherwise `ERR_CLAIM_NOT_CLOSABLE`), its latest-recorded determination is `FINAL` (otherwise `ERR_DETERMINATION_NOT_FINAL`), and no appeal remains in `FILED`, `DOCKETED`, or `HEARD` (otherwise `ERR_APPEAL_IN_FLIGHT`). The claim becomes `CLOSED` — terminal, like `WITHDRAWN` — and the employer's `compliance_posture` is recomputed.

### 3.6. Charge Statements, Line Protests, and Reconciliation

Each quarter the state issues a charge statement, recorded by an `AgencyLiaison` with the charged `employer_id`, the issuing `state_code`, the `quarter` (a string in the format of a four-digit year followed by Q and a digit from 1 to 4, such as `2026Q2`), and the `issued_at` date. The statement's `protest_due_at` is the date part of `issued_at` plus the state's `protest_window_days` calendar days — again always calendar days — with `weekend_shift` applied and the 17:00:00 UTC pin. The statement opens in `ISSUED` with `total_charged_cents` at zero and carries the five audit aggregates — `audited_total_cents`, `erroneous_total_cents`, `protested_total_cents`, `reversed_total_cents`, and `variance_cents` — all zero at issuance.

Charge lines are posted onto the statement by an `AgencyLiaison`, each carrying its `statement_id`, the `claim_id` whose benefits produced the charge, the `amount_cents` charged (which must be non-negative, otherwise `ERR_FISCAL_CAP_EXCEEDED`), the `benefit_weeks` the line covers, and an optional `erroneous_reason` — `NONE` (the default), `CLAIMANT_NOT_SEPARATED`, `WRONG_EMPLOYER`, `ALREADY_PROTESTED`, `EXCEEDS_MAX_BENEFIT`, or `DUPLICATE_LINE`. Posting a line moves three ledgers at once: the statement's `total_charged_cents` increases by the amount, the claim's `charged_amount_cents` increases by the amount, and the employer's `reserve_balance_cents` decreases by the amount — the reserve is debited when the charge posts. The statement's `version` increments by one with each posting. One fiscal cap guards the posting: the claim's `charged_amount_cents` may not be pushed above its `max_benefit_cents` (otherwise `ERR_MAX_BENEFIT_EXCEEDED`). The named claim must belong to the statement's employer (otherwise `ERR_CROSS_PARENT_REFERENCE`), but posting does not consult the claim's determination outcome — any claim of the statement's employer may be charged. Each line opens in `PENDING`.

Audit is the employer's instrument, worked by a `ChargeAuditor`. Opening an audit requires the statement to be `ISSUED` (otherwise `ERR_STATEMENT_NOT_AUDITABLE`) and moves it to `UNDER_AUDIT`, recomputing the audit variance over its lines. The variance computation keeps five aggregates, stored on the statement as `audited_total_cents`, `erroneous_total_cents`, `protested_total_cents`, `reversed_total_cents`, and `variance_cents`: the audited total, summing the amounts of lines in `PENDING` or `SUSTAINED`; the erroneous total, summing lines whose `erroneous_reason` is not `NONE`; the protested total over lines in `PROTESTED`; the reversed total over lines in `REVERSED`; and the `variance_cents` figure — the erroneous total minus the reversed total — which measures unrecovered erroneous exposure. The same recomputation synchronizes the statement's `total_charged_cents` to the sum of every line still standing charged — all lines not `REVERSED` or `WAIVED`, so `PROTESTED` lines remain included while their protest is open and reversed and waived lines never linger in the ledger. The variance recomputes at audit open, at audit completion, on every line posting, and on every line status change. Completing the audit requires the statement to be `UNDER_AUDIT` (otherwise `ERR_INVALID_STATE`) and that no line on the statement is still `PROTESTED` (otherwise `ERR_PROTESTS_IN_FLIGHT`); it moves the statement to `AUDIT_COMPLETE` with an audit-findings snapshot and the erroneous totals aggregated.

The charge protest is how erroneous lines are attacked. A `ChargeAuditor` files a protest against a line in `PENDING` (otherwise `ERR_LINE_NOT_PROTESTABLE`), naming the `line_item_id`, the parent `statement_id` (denormalized onto the protest), and a `protest_basis` drawn from the erroneous-reason domain excluding `NONE` — `CLAIMANT_NOT_SEPARATED`, `WRONG_EMPLOYER`, `ALREADY_PROTESTED`, `EXCEEDS_MAX_BENEFIT`, or `DUPLICATE_LINE`. Filing must happen at or before the statement's `protest_due_at`, equality counting as on time; a late filing is stamped and moved straight to `DISMISSED_UNTIMELY` — its `evidence_strength` is not computed and remains zero, and the line and statement are left untouched. Two protest-specific rules protect the line: a basis of `ALREADY_PROTESTED` is allowed only when a prior protest on the same line was `DENIED` (otherwise `ERR_LINE_ALREADY_PROTESTED`), and at most one open — `FILED` or `UNDER_REVIEW` — protest may exist per line (a second one is rejected with `ERR_DUPLICATE_ACTIVE_RECORD`). The request must also carry `expected_statement_version` per §2.9, and filing increments the statement's `version` by one. A filed protest opens in `FILED` with `filed_at` stamped and `timeliness` computed, the line moves from `PENDING` to `PROTESTED`, the protest's `evidence_strength` is computed, and a statement still in `ISSUED` bubbles up to `UNDER_AUDIT` automatically.

Evidence strength is scored in a pinned order at protest creation. The score starts from the basis weight: 50 for `CLAIMANT_NOT_SEPARATED`, 70 for `WRONG_EMPLOYER`, 30 for `ALREADY_PROTESTED`, 60 for `EXCEEDS_MAX_BENEFIT`, and 65 for `DUPLICATE_LINE`. If the claim has any determination with outcome `DENIED` — the agency has already sided with the employer once — the score gains 20. Next, the claim's latest-filed response among those in `SUBMITTED`, `ACCEPTED`, or `REJECTED_INSUFFICIENT` is located, with a tie on `filed_at` broken in favor of the row with the later `created_at` and any further tie broken in favor of the later-created row; if that response exists and its `timeliness` is `LATE`, the score loses 25, and if no such response exists no timeliness term applies at all. Then the separation's coding confidence applies: `CONFIRMED` adds 10 and `DISPUTED` subtracts 10. The result is clamped into the range from zero to one hundred and stored as `evidence_strength`.

Adjudication of protests belongs to the `AgencyLiaison`. Opening review moves a `FILED` protest to `UNDER_REVIEW` (otherwise `ERR_PROTEST_NOT_REVIEWABLE`). Sustaining requires the protest to be `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`) with an `evidence_strength` of at least 60 (otherwise `ERR_PROTEST_EVIDENCE_WEAK`); the protest becomes `SUSTAINED` and the line becomes `REVERSED`, running the full reversal cascade — statement total and claim charged amount each decremented by the line's amount, employer reserve credited by the same. Denying likewise requires the protest to be `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`); it moves the protest to `DENIED` and the line to `SUSTAINED`, and the denial counts half a strike in the employer's posture recompute per §2.10. A `ChargeAuditor` may withdraw a protest from `FILED` or `UNDER_REVIEW` (any other status yields `ERR_INVALID_STATE`); the protest becomes `WITHDRAWN` and the line returns to `PENDING`, a compensating action restoring the pre-protest ledger posture.

The agency may also simply waive a pending line. An `AgencyLiaison` waiving a line in `PENDING` (otherwise `ERR_LINE_NOT_WAIVABLE`) moves it to `WAIVED` and applies the same three-ledger adjustment as a reversal — statement total down, claim charged down, employer reserve up, each by the line's amount — but no `protest_credits_cents` accrue, because a waive is agency goodwill rather than an employer protest win.

Reconciliation is the statement's terminal act, performed by a `ChargeAuditor`. The statement must be `AUDIT_COMPLETE` (otherwise `ERR_STATEMENT_NOT_RECONCILABLE`), and no protest on any of its lines may remain in `FILED` or `UNDER_REVIEW` (otherwise `ERR_PROTESTS_IN_FLIGHT`). Reconciliation moves the statement to `RECONCILED` and credits the employer's `protest_credits_cents` by the sum of the amounts of its `REVERSED` lines — the audit-trail credit counter. It performs no additional reserve movement whatsoever: the reserve was already credited at each line's `REVERSED` transition, and a second credit is forbidden. Finally, all of the employer's experience-rating models — `DRAFT` and `FINALIZED` alike, whatever their model year — move to `SUPERSEDED`, their derived inputs now stale, and the employer's `current_tax_rate_bps` is re-evaluated immediately per §3.7.

### 3.7. Experience Rating Projection and the Compliance Posture

The experience-rating model lets the employer see its tax rate coming. A `RatingAnalyst` creates a model for an employer — referencing it via `employer_id` — with a `model_year`, a `variant` of `RESERVE_RATIO` or `BENEFIT_RATIO`, and a `kind` of `OFFICIAL` or `WHAT_IF`. Creation runs the projection immediately: `projected_rate_bps` and `projected_liability_cents` are computed, an `input_snapshot_hash` of the charged inputs at computation time — the variant, the summed benefit charges, the reserve balance, the taxable payroll, and the compliance posture — is stored, and the model opens in `DRAFT`.

The projection itself follows a pinned evaluation order. First, benefit charges are summed: the amounts of every charge line on the employer's claims whose status is `PENDING` or `SUSTAINED` — `REVERSED` and `WAIVED` lines are excluded. Second, the ratio is computed per variant. Under the `RESERVE_RATIO` variant the ratio is the employer's `reserve_balance_cents` divided by its `taxable_payroll_cents`; a higher reserve yields a lower ratio and therefore a lower rate, and because the reserve ledger is already net of benefit charges, those charges enter through the reserve alone — counting them again is forbidden. Under the `BENEFIT_RATIO` variant the ratio is the benefit charges divided by `taxable_payroll_cents`; here higher charges yield a higher ratio and a higher rate, the reverse direction, so identical inputs produce a different rate under the two variants. If `taxable_payroll_cents` is zero, the ratio is taken as exactly zero when the numerator is also zero and as a value above every ceiling otherwise. Third, the unrounded ratio selects a base rate from the rate table by taking the first row whose ceiling is greater than or equal to the ratio: a ratio at or below −0.05 maps to 60 basis points; above −0.05 and at or below 0.00, to 120; above 0.00 and at or below 0.02, to 180; above 0.02 and at or below 0.04, to 270; above 0.04 and at or below 0.06, to 360; above 0.06 and at or below 0.08, to 450; and anything higher falls into the top band — the final row, ceiling 1.00 — at 540 basis points. Fourth, posture surcharges apply: a `SANCTIONED` employer adds 50 basis points, a `WATCH` employer adds 20, and a `CLEAR` employer adds nothing. Fifth, the projected rate is the surcharged rate capped at 540 basis points. Sixth and last, `projected_liability_cents` is the integer projected rate multiplied by `taxable_payroll_cents`, divided by ten thousand, and rounded down to a whole cent. The rounding order is pinned: the ratio stays an exact rational through tiering, and only the final liability is rounded — down.

Finalization is guarded three ways. The model must be `DRAFT` (otherwise `ERR_MODEL_NOT_DRAFT`); an `OFFICIAL` model's `variant` must match the employer's `merit_rating_method` (otherwise `ERR_MODEL_VARIANT_MISMATCH`), while the other variant remains computable as a `WHAT_IF` comparison; and the stored `input_snapshot_hash` must still match the current inputs (otherwise `ERR_MODEL_INPUT_STALE`). The request must carry `expected_employer_version` matching the employer's current `version` per §2.9, because finalization supersedes the prior `FINALIZED` `OFFICIAL` model for the same employer and year — a create-with-supersede that leaves exactly one finalized official model per employer and year, an invariant whose violation surfaces as `ERR_DUPLICATE_ACTIVE_RECORD`. Finalization moves the model to `FINALIZED` and increments the employer's `version` by one. Models also leave `DRAFT` for `SUPERSEDED` when a source charge or payroll input changes before finalize, and a `FINALIZED` model becomes `SUPERSEDED` when a later official model finalizes or a charge reconciliation mutates its inputs. The projection's output refreshes the employer's `current_tax_rate_bps` — always evaluated under the employer's own `merit_rating_method`, whatever variant the model being created carries — and it is re-evaluated when a model is created, when a charge statement is reconciled, and whenever the payroll input changes.

The compliance posture closes the loop. As §2.10 defines, the effective strike count — `late_response_strikes` plus a half strike per denied protest — maps to `CLEAR`, `WATCH`, or `SANCTIONED` at the inclusive thresholds of two and four, recomputed on every late response, every protest denial, and every claim closure. Posture in turn feeds the rating surcharge above. A computed read, the employer's rating summary, exposes the current standing in one place — its data carries exactly `current_tax_rate_bps`, `compliance_posture`, `late_response_strikes`, and `protest_credits_cents`.

## 4. Endpoint Definitions

Operations that create new resources — registering a state rule, creating an employer, engaging a TPA, recording a separation or claim, drafting a response, attaching evidence, recording a determination, filing an appeal, scheduling a hearing, adding a witness, issuing a statement, posting a line, filing a protest, creating a rating model — return `201 Created`. Operations that act on an existing resource without creating a new one — submissions, decisions, status actions, continuations, clock control, and the acknowledgment capability — return `200 OK`. Removing an evidence document returns `204 No Content` with no data. The table below is a summary only; the complete request and response semantics for each operation are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/_events/claim_adjudication_ack` | Simulate agency acknowledgment of a submitted response | PlatformAdmin |
| POST | `/ui/state-rules` | Register a state's deadline rules | PlatformAdmin |
| GET | `/ui/state-rules` | List state rules | PlatformAdmin, ClaimsAnalyst, TpaAgent, ChargeAuditor, AgencyLiaison, RatingAnalyst, TpaManager |
| GET | `/ui/state-rules/{id}` | Get one state rule | PlatformAdmin, ClaimsAnalyst, TpaAgent, ChargeAuditor, AgencyLiaison, RatingAnalyst, TpaManager |
| POST | `/ui/employers` | Create employer account | PlatformAdmin |
| GET | `/ui/employers` | List employers | PlatformAdmin, ClaimsAnalyst, ChargeAuditor, RatingAnalyst, TpaManager |
| GET | `/ui/employers/{id}` | Get employer | PlatformAdmin, ClaimsAnalyst, ChargeAuditor, RatingAnalyst, TpaManager |
| GET | `/ui/employers/{id}/claims` | Claims for an employer | PlatformAdmin, ClaimsAnalyst, ChargeAuditor, AgencyLiaison |
| GET | `/ui/employers/{id}/separations` | Separations for an employer | PlatformAdmin, ClaimsAnalyst, AgencyLiaison |
| GET | `/ui/employers/{id}/charge-statements` | Charge statements for an employer | PlatformAdmin, ChargeAuditor |
| GET | `/ui/employers/{id}/experience-rating-models` | Rating models for an employer | PlatformAdmin, RatingAnalyst |
| GET | `/ui/employers/{id}/tpa-engagements` | TPA engagements for an employer | PlatformAdmin, TpaManager, ClaimsAnalyst |
| POST | `/ui/tpa-engagements` | Engage a TPA for an employer | TpaManager |
| GET | `/ui/tpa-engagements/{id}` | Get engagement | PlatformAdmin, TpaManager, ClaimsAnalyst |
| POST | `/ui/tpa-engagements/{id}/suspend` | Suspend engagement | TpaManager |
| POST | `/ui/tpa-engagements/{id}/reinstate` | Reinstate with remediation note | TpaManager |
| POST | `/ui/tpa-engagements/{id}/terminate` | Terminate engagement | TpaManager |
| POST | `/ui/separations` | Record a claimant separation | ClaimsAnalyst |
| GET | `/ui/separations/{id}` | Get separation | PlatformAdmin, ClaimsAnalyst, AgencyLiaison |
| POST | `/ui/separations/{id}/coding/confirm` | Confirm reason coding (evidence-gated for misconduct) | ClaimsAnalyst |
| POST | `/ui/claims` | Claim notice intake | ClaimsAnalyst, AgencyLiaison |
| GET | `/ui/claims` | List claims (filterable) | PlatformAdmin, ClaimsAnalyst, TpaAgent, ChargeAuditor, AgencyLiaison |
| GET | `/ui/claims/{id}` | Get claim | PlatformAdmin, ClaimsAnalyst, TpaAgent, ChargeAuditor, AgencyLiaison |
| GET | `/ui/claims/{id}/responses` | Responses for a claim | PlatformAdmin, ClaimsAnalyst, TpaAgent, AgencyLiaison |
| GET | `/ui/claims/{id}/evidence` | Evidence for a claim | PlatformAdmin, ClaimsAnalyst, TpaAgent, AgencyLiaison |
| GET | `/ui/claims/{id}/determinations` | Determinations for a claim | PlatformAdmin, ClaimsAnalyst, AgencyLiaison |
| GET | `/ui/claims/{id}/hearings` | Hearings for a claim | PlatformAdmin, ClaimsAnalyst, AgencyLiaison |
| POST | `/ui/claims/{id}/withdraw` | Withdraw claim notice | AgencyLiaison |
| POST | `/ui/claims/{id}/close` | Close a determined claim | ClaimsAnalyst |
| POST | `/ui/claims/{id}/responses` | Draft a claim response | ClaimsAnalyst, TpaAgent |
| GET | `/ui/responses/{id}` | Get response | PlatformAdmin, ClaimsAnalyst, TpaAgent, AgencyLiaison |
| GET | `/ui/responses/{id}/amendments` | Responses amending this response | PlatformAdmin, ClaimsAnalyst, TpaAgent, AgencyLiaison |
| GET | `/ui/responses/{id}/evidence` | Evidence attached to this response | PlatformAdmin, ClaimsAnalyst, TpaAgent, AgencyLiaison |
| GET | `/ui/tpa-engagements/{id}/responses` | Responses filed under this engagement | PlatformAdmin, TpaManager, ClaimsAnalyst |
| GET | `/ui/claims/{id}/charge-line-items` | Charge lines attributed to this claim | PlatformAdmin, ClaimsAnalyst, ChargeAuditor, AgencyLiaison |
| POST | `/ui/claims/{id}/responses/{rid}/submit` | Submit response (OCC on claim) | ClaimsAnalyst, TpaAgent |
| POST | `/ui/claims/{id}/responses/{rid}/accept` | Agency accepts response | AgencyLiaison |
| POST | `/ui/claims/{id}/responses/{rid}/reject` | Agency rejects response as insufficient | AgencyLiaison |
| POST | `/ui/claims/{id}/evidence` | Attach evidence document | ClaimsAnalyst, TpaAgent |
| DELETE | `/ui/evidence/{id}` | Remove evidence document | ClaimsAnalyst |
| POST | `/ui/claims/{id}/determinations` | Record agency determination | AgencyLiaison |
| GET | `/ui/determinations/{id}` | Get determination | PlatformAdmin, ClaimsAnalyst, AgencyLiaison, RatingAnalyst |
| GET | `/ui/determinations/{id}/appeals` | Appeals of a determination | PlatformAdmin, ClaimsAnalyst, AgencyLiaison |
| POST | `/ui/determinations/{id}/appeals` | File an appeal | ClaimsAnalyst, AgencyLiaison |
| GET | `/ui/appeals/{id}` | Get appeal | PlatformAdmin, ClaimsAnalyst, AgencyLiaison |
| GET | `/ui/appeals/{id}/hearings` | Hearings for an appeal | PlatformAdmin, ClaimsAnalyst, AgencyLiaison |
| POST | `/ui/appeals/{id}/withdraw` | Withdraw appeal | ClaimsAnalyst |
| POST | `/ui/appeals/{id}/decide` | Record appeal decision | AgencyLiaison |
| POST | `/ui/appeals/{id}/hearings` | Schedule hearing (dockets the appeal) | ClaimsAnalyst |
| GET | `/ui/hearings/{id}` | Get hearing | PlatformAdmin, ClaimsAnalyst, AgencyLiaison |
| GET | `/ui/hearings/{id}/witnesses` | Witnesses for a hearing | PlatformAdmin, ClaimsAnalyst, AgencyLiaison |
| POST | `/ui/hearings/{id}/witnesses` | Add witness (starts prep) | ClaimsAnalyst |
| POST | `/ui/hearings/{id}/witnesses/{wid}/prep` | Advance witness prep one step | ClaimsAnalyst |
| POST | `/ui/hearings/{id}/continue` | Request continuance (reschedule) | ClaimsAnalyst |
| POST | `/ui/hearings/{id}/hold` | Mark hearing held | AgencyLiaison |
| POST | `/ui/charge-statements` | Issue a quarterly charge statement | AgencyLiaison |
| GET | `/ui/charge-statements/{id}` | Get statement | PlatformAdmin, ChargeAuditor, AgencyLiaison |
| GET | `/ui/charge-statements/{id}/line-items` | Lines of a statement | PlatformAdmin, ChargeAuditor, AgencyLiaison |
| GET | `/ui/charge-statements/{id}/protests` | Protests on a statement | PlatformAdmin, ChargeAuditor, AgencyLiaison |
| POST | `/ui/charge-statements/{id}/line-items` | Post a charge line | AgencyLiaison |
| POST | `/ui/charge-statements/{id}/audit` | Open audit | ChargeAuditor |
| POST | `/ui/charge-statements/{id}/audit/complete` | Complete audit | ChargeAuditor |
| POST | `/ui/charge-statements/{id}/reconcile` | Reconcile statement into employer ledger | ChargeAuditor |
| GET | `/ui/charge-line-items/{id}` | Get line item | PlatformAdmin, ChargeAuditor, AgencyLiaison |
| GET | `/ui/charge-line-items/{id}/protests` | Protests on a line | PlatformAdmin, ChargeAuditor, AgencyLiaison |
| POST | `/ui/charge-line-items/{id}/protests` | File charge protest (OCC on statement) | ChargeAuditor |
| POST | `/ui/charge-line-items/{id}/waive` | Agency waives a pending charge line | AgencyLiaison |
| GET | `/ui/charge-protests/{id}` | Get protest | PlatformAdmin, ChargeAuditor, AgencyLiaison |
| POST | `/ui/charge-protests/{id}/review` | Open protest review | AgencyLiaison |
| POST | `/ui/charge-protests/{id}/sustain` | Sustain protest | AgencyLiaison |
| POST | `/ui/charge-protests/{id}/deny` | Deny protest | AgencyLiaison |
| POST | `/ui/charge-protests/{id}/withdraw` | Withdraw protest | ChargeAuditor |
| POST | `/ui/employers/{id}/experience-rating-models` | Create a rating projection model | RatingAnalyst |
| GET | `/ui/experience-rating-models/{id}` | Get model | PlatformAdmin, RatingAnalyst |
| POST | `/ui/employers/{id}/experience-rating-models/{mid}/finalize` | Finalize model (OCC on employer; supersedes prior official) | RatingAnalyst |
| GET | `/ui/employers/{id}/rating-summary` | Computed read: current rate, posture, strikes, credits | PlatformAdmin, RatingAnalyst, ChargeAuditor |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CROSS_PARENT_REFERENCE` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CLAIM_NOT_RESPONSIVE` | 409 Conflict |
| `ERR_RESPONSE_NOT_DRAFT` | 409 Conflict |
| `ERR_RESPONSE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_RESPONSE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_UNDER_ADJUDICATION` | 409 Conflict |
| `ERR_CLAIM_NOT_CLOSABLE` | 409 Conflict |
| `ERR_CLAIM_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_DETERMINATION_NOT_APPEALABLE` | 409 Conflict |
| `ERR_DETERMINATION_NOT_FINAL` | 409 Conflict |
| `ERR_APPEAL_IN_FLIGHT` | 409 Conflict |
| `ERR_APPEAL_NOT_DOCKETABLE` | 409 Conflict |
| `ERR_APPEAL_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_APPEAL_NOT_HEARD` | 409 Conflict |
| `ERR_HEARING_NOT_READY` | 409 Conflict |
| `ERR_REFEREE_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_WITNESS_UNAVAILABLE` | 409 Conflict |
| `ERR_CONTINUANCE_LIMIT` | 409 Conflict |
| `ERR_TPA_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_TPA_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_TPA_NOT_ACTIVE` | 403 Forbidden |
| `ERR_AUTHORITY_VIOLATION` | 403 Forbidden |
| `ERR_TPA_NOT_SUSPENDED` | 409 Conflict |
| `ERR_TPA_HAS_OPEN_WORK` | 409 Conflict |
| `ERR_REMEDIATION_NOTE_SHORT` | 422 Unprocessable Entity |
| `ERR_CODING_EVIDENCE_MISSING` | 422 Unprocessable Entity |
| `ERR_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_STATEMENT_NOT_AUDITABLE` | 409 Conflict |
| `ERR_STATEMENT_NOT_RECONCILABLE` | 409 Conflict |
| `ERR_PROTESTS_IN_FLIGHT` | 409 Conflict |
| `ERR_LINE_NOT_PROTESTABLE` | 409 Conflict |
| `ERR_LINE_NOT_WAIVABLE` | 409 Conflict |
| `ERR_LINE_ALREADY_PROTESTED` | 409 Conflict |
| `ERR_PROTEST_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_PROTEST_EVIDENCE_WEAK` | 422 Unprocessable Entity |
| `ERR_MAX_BENEFIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FISCAL_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_RECORD` | 409 Conflict |
| `ERR_MODEL_NOT_DRAFT` | 409 Conflict |
| `ERR_MODEL_VARIANT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MODEL_INPUT_STALE` | 409 Conflict |
