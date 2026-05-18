# Patent Application Filing API — Product Requirements Document

## 1. Introduction

Patent prosecution before the United States Patent and Trademark Office (USPTO) is a long-running, fee-sensitive, deadline-driven workflow that interleaves three different parties — the **applicant**, the **examiner**, and the **platform administrator** — over time spans that range from a few weeks to two decades. A single application moves through a sequence of legally significant states (draft, filed, under examination, office-action pending, allowed, granted, abandoned, expired), accumulates a layered fee history that must precisely match a published schedule discounted by entity size (large, small, micro), and may spawn child filings (continuations, continuations-in-part) or branch into the international Patent Cooperation Treaty (PCT) track with its own thirty-month national-phase deadline. Granted utility patents further trigger three scheduled maintenance windows whose lapse silently expires the patent.

This API formalises that workflow as an explicit state machine with strict segregation of duties between the three roles, deterministic fee computation against the official table, server-side deadline enforcement driven by a controllable logical clock, and an immutable audit trail for every state-affecting action. The objective is to replace the informal, paper-driven prosecution timeline with a system in which every fee mismatch, premature transition, or missed deadline is detected and reported deterministically, so that downstream auditors, applicants, and examiners can rely on the API's response as the authoritative record of where each filing stands and what is required to advance it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, identifying which of the three roles that principal is acting as. Absence of either header causes the request to be rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose `X-User-Role` is not exactly one of `Applicant`, `Examiner`, or `USPTOAdmin`, or whose role is not authorised for the requested operation per the endpoint table in §4, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles are:

- **`Applicant`** — the end-user inventor or filing organisation. When `X-User-Role` is `Applicant`, the value of `X-User-ID` is the `id` of the acting `Applicant` row in the database; every ownership check on an applicant-scoped resource (an `Application`, `OfficeAction`, `MaintenanceFee`, `PCTPhase`, `FeeTransaction`, or `Response`) compares the resource's owning `applicant_id` to `X-User-ID`, and a mismatch is also reported as `ERR_FORBIDDEN`. An `Applicant` may not invoke any examination action and may not perform any administrative action.
- **`Examiner`** — a USPTO examiner. When `X-User-Role` is `Examiner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, in `AuditEvent.actor_id`) but does not compare it to any entity's `id`. An `Examiner` may begin examination, issue Office Actions, allow, and grant applications across all applicants, but may not pay fees on an applicant's behalf nor file or abandon an applicant's application.
- **`USPTOAdmin`** — the platform operator. When `X-User-Role` is `USPTOAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it is recorded in audit but never used as an ownership key. A `USPTOAdmin` owns applicant CRUD and clock advancement and reads any resource; the admin cannot perform any examiner action and cannot perform applicant write actions on applications — this segregation of duties is enforced unconditionally.

Authorisation is evaluated before any state, business, or fee check, in the order: header presence (`ERR_UNAUTHENTICATED`), role enumeration (`ERR_FORBIDDEN`), role-operation permission (`ERR_FORBIDDEN`), path-resource existence (`ERR_NOT_FOUND`, validated left-to-right), and finally ownership (`ERR_FORBIDDEN`).

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter defaults to 0 and has no upper bound beyond the available `total_count`. Results from every list endpoint are sorted by `created_at` in ascending order. Each list response's `meta` block surfaces `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true when `offset + limit < total_count`.

### 2.4. Common Resource Properties

Every persisted entity except the immutable audit ledger and the in-memory clock — that is, every `Applicant`, `Application`, `OfficeAction`, `Response`, `MaintenanceFee`, and `PCTPhase` — exposes four standard properties: a server-minted `id` formatted as a UUID without any type prefix, an ISO 8601 UTC `created_at` timestamp with three fractional digits, an ISO 8601 UTC `updated_at` timestamp that is refreshed on every mutation, and an integer `version` that begins at 1 on creation and increments by exactly 1 on every mutation. The two append-only ledger entities — `FeeTransaction` and `AuditEvent` — carry only `id` and `created_at`; they have no `updated_at` and no `version` because they are never mutated after insertion. `SystemClock` is a singleton resource whose only field is `now`; it likewise has neither `updated_at` nor `version`.

### 2.5. Optimistic Concurrency Control

Mutation endpoints that accept a `version` field (`PATCH /applicants/{id}` and `PATCH /applications/{id}`) treat that field as optional: if a `version` value is omitted from the request body, no concurrency check is performed and the mutation proceeds against whatever the current row holds; if a `version` value is supplied, it must equal the entity's current `version` exactly, and any other value causes the request to be rejected with `ERR_VERSION_CONFLICT` (HTTP 409). Successful mutations increment `version` by 1 and refresh `updated_at`. Several action-style transitions — `file`, `begin-examination`, `allow`, `grant`, `abandon`, the office-action issuance, the response filing, the maintenance fee payment, and the PCT national-phase entry — also serialise via first-writer-wins on the target entity's `status` and `version`; the loser of a race on these endpoints receives `ERR_INVALID_STATE` (see §2.10).

### 2.6. Nested Resource Validation

Endpoints whose paths contain more than one identifier — for example, those nested under `/applications/{id}/fees`, `/applications/{id}/office-actions`, or `/applications/{id}/maintenance-fees` — validate path segments strictly left to right. The outer resource is resolved first; if it does not exist, `ERR_NOT_FOUND` is returned without examining the inner segment. Only if the outer resource exists is the inner identifier resolved. The same left-to-right rule applies to `/office-actions/{id}/responses`, `/maintenance-fees/{id}/pay`, and `/pct-phases/{id}/enter-national`.

### 2.7. Monetary Precision and Fee Schedule

All monetary fields are stored and exchanged as **integer USD cents**; no fractional cents are ever permitted on the wire or at rest. Every fee computation in §3 follows the same precision contract: intermediate multiplication by the entity-size multiplier is rounded to integer cents using the **round-half-up** rule. The entity-size multiplier is 1.00 for `LARGE` applicants, 0.50 for `SMALL` applicants, and 0.25 for `MICRO` applicants. The exact rounding location within each formula (per component vs. on the sum vs. after surcharge addition) is fee-specific and is spelled out in the relevant §3 subsection — implementers must respect the pinned order, because rounding before vs. after summation produces different integer-cent results at odd counts.

### 2.8. Logical Clock and Time-Gated Sweeps

The server runs against a logical clock, `SystemClock.now`, that is initialised by the deployment and advanced exclusively by an admin-only test-driving capability that accepts a target `to` instant. Every deadline in the system — Office Action response deadlines, maintenance fee grace windows, PCT national-phase deadlines, statutory patent terms — is evaluated against `SystemClock.now` rather than wall-clock time. When the admin advances the clock, the server runs a deterministic sweep that, in one logical step: transitions every `OfficeAction` whose `extended_deadline_at` is before the new `now` and is still `PENDING` to `ABANDONED_BY_DEFAULT` (and cascades its parent `Application` to `ABANDONED`); transitions every `MaintenanceFee` whose `grace_period_end_at` is before the new `now` and that has received no qualifying payment to `LAPSED` (and propagates the parent `Application` to `EXPIRED`); transitions every `PCTPhase` whose `national_phase_deadline_at` is before the new `now` and that is still `INTERNATIONAL` to `LAPSED`; and transitions every granted `Application` whose `expires_at` is at or before the new `now` to `EXPIRED`. The clock may only move forward; reading the current clock is open to every authenticated role.

### 2.9. Hierarchical Consistency, Cascades, and Audit

Every state transition writes an `AuditEvent` row whose `application_id` ties the event to the relevant filing, whose `actor_role` records the role that initiated the action, whose `actor_id` records the supplied `X-User-ID`, whose `action` is a symbolic identifier (such as `APPLICATION_FILED`, `EXAMINATION_BEGUN`, `OFFICE_ACTION_ISSUED`, `OFFICE_ACTION_RESPONDED`, `APPLICATION_ABANDONED_DEADLINE`, `APPLICATION_ABANDONED_VOLUNTARY`, `APPLICATION_ALLOWED`, `APPLICATION_GRANTED`, `APPLICATION_EXPIRED`, `APPLICATION_DRAFTED`, `MAINTENANCE_FEE_PAID`, `MAINTENANCE_FEE_LAPSED`, `PCT_NATIONAL_ENTERED`, or `PCT_LAPSED`), and whose `details` is a structured object describing the change. Audit rows are immutable and append-only; they are never updated or deleted. Whenever any mutating transition runs against an entity, that entity's `version` is incremented by 1 and its `updated_at` is refreshed; the same is true of cascaded mutations (e.g., when voluntary abandonment moves an Office Action from `PENDING` to `ABANDONED_BY_DEFAULT`, that Office Action's `version` and `updated_at` are bumped). The denormalised aggregate `Application.total_fees_paid_cents` is recomputed on every `FeeTransaction` insertion as the sum of every `FeeTransaction.amount_cents` row whose `application_id` matches, ordered by `paid_at` ascending with ties broken by `FeeTransaction.id` ascending; because the transaction ledger is append-only there is no status filter on this aggregate.

### 2.10. Concurrency Semantics for State-Affecting Operations

Five concurrency contracts apply uniformly across state-affecting endpoints:

- Two examiners simultaneously beginning examination on the same `FILED` application serialise on the application's `status` and `version`. At most one transition to `UNDER_EXAMINATION` succeeds; the loser receives `ERR_INVALID_STATE` because the application's `status` is no longer `FILED` at commit time.
- An applicant paying a maintenance fee at the same instant the clock-advance sweep is evaluating the same `MaintenanceFee` at the grace boundary likewise serialises on `MaintenanceFee.status`. If the payment commits at a moment when `SystemClock.now` is at or before `grace_period_end_at`, the payment wins; otherwise the sweep wins and the payment is rejected with `ERR_MAINTENANCE_WINDOW_CLOSED`.
- An applicant filing a Response while the sweep is evaluating the `extended_deadline_at` of the same Office Action serialises on `OfficeAction.status`. If the response commits at a moment when `SystemClock.now` is at or before `extended_deadline_at`, the response wins; otherwise the sweep wins and the response is rejected with `ERR_OFFICE_ACTION_DEADLINE_PASSED`.
- Two simultaneous continuation or CIP filings referencing the same non-`PROVISIONAL` parent that has just been abandoned read-validate-write on the parent's `status` at the file commit. The continuation whose commit sees a parent whose `status` is no longer one of `FILED`, `UNDER_EXAMINATION`, `OFFICE_ACTION_PENDING`, `ALLOWED`, or `GRANTED` is rejected with `ERR_PARENT_NOT_PENDING`.
- Two grant calls racing on the same `ALLOWED` application after the issue fee has been paid serialise on the application's `status` and `version`. At most one transition to `GRANTED` succeeds; the loser receives `ERR_INVALID_STATE`.

### 2.11. Validation Priority

Validation across every endpoint runs in a fixed priority order, evaluated top-down so that an earlier failure short-circuits later checks: (1) header presence yields `ERR_UNAUTHENTICATED`; (2) role-enum membership yields `ERR_FORBIDDEN`; (3) role-operation permission yields `ERR_FORBIDDEN`; (4) path-resource existence yields `ERR_NOT_FOUND`; (5) ownership for applicant-scoped endpoints yields `ERR_FORBIDDEN`; (6) state-machine preconditions yield `ERR_INVALID_STATE`; (7) the continuation-parent precondition yields `ERR_PARENT_NOT_PENDING`; (8) the micro-entity eligibility precondition yields `ERR_MICRO_INELIGIBLE`; (9) the claim-shape precondition yields `ERR_CLAIM_SHAPE_INVALID`; (10) the Office Action temporal precondition yields `ERR_OFFICE_ACTION_DEADLINE_PASSED`; (11) the maintenance temporal precondition yields `ERR_MAINTENANCE_WINDOW_CLOSED`; (12) the PCT temporal precondition yields `ERR_PCT_DEADLINE_PASSED`; (13) the fee-amount precondition yields `ERR_FEE_AMOUNT_MISMATCH`; (14) the fee-category appropriateness precondition yields `ERR_FEE_CATEGORY_INVALID`; (15) the applicant-active precondition yields `ERR_APPLICANT_SUSPENDED`; (16) the PCT eligibility precondition yields `ERR_PCT_INELIGIBLE`; (17) the maintenance-applicability precondition yields `ERR_MAINTENANCE_NOT_APPLICABLE`; (18) the idempotency-conflict check yields `ERR_IDEMPOTENCY_CONFLICT`; (19) optimistic-concurrency mismatch yields `ERR_VERSION_CONFLICT`. Generic input shape or enum-value failures that do not match any of these priority slots are reported as `ERR_VALIDATION`. The fixed order matters: a `SUSPENDED` applicant attempting a state-affecting action sees `ERR_APPLICANT_SUSPENDED` only after the state-machine, claim, fee, and temporal checks have passed, because those earlier categories diagnose the request shape itself.

### 2.12. Idempotency

The endpoints that create a `FeeTransaction` (under the application's fee-recording capability) and the application file transition accept an optional `X-Idempotency-Key` header. When supplied, the server caches the original response keyed by the tuple of route, key, and acting `applicant_id` for 24 hours. A replay with the same tuple returns the cached response; a replay with the same tuple but a different payload is rejected with `ERR_IDEMPOTENCY_CONFLICT`. Endpoints not in the idempotency-eligible set ignore the header.

## 3. Business Logic & Workflows

### 3.1. Applicant Registration, Risk Scoring, and Suspension

Every patent filing originates from an `Applicant`, which the platform admin registers by supplying the applicant's legal `name` and the USPTO-recognised entity-size classification `entity_size`, which must be one of `LARGE`, `SMALL`, or `MICRO`. Two additional fields, `gross_income_cents` and `prior_filings_count`, are optional in general but become mandatory when `entity_size` is `MICRO`: the registration is rejected with `ERR_MICRO_INELIGIBLE` unless both income and prior-filings figures are present and within the published caps. Both caps are non-negative integers. A newly created applicant's lifecycle field `status` defaults to `ACTIVE`. The applicant detail endpoint, in addition to returning the stored applicant fields, recomputes a derived **applicant risk score** on every read; the same admin-driven applicant update also accepts a `name`, an `entity_size`, a `gross_income_cents`, and a `prior_filings_count`, optionally paired with a `version` for concurrency control.

The risk score is an integer in the closed range from 0 to 100 expressing how likely the applicant is to lapse their patent portfolio. It is computed by summing three weighted counts: each `MaintenanceFee` whose owning `Application` belongs to this applicant and whose `status` is `LAPSED` contributes a weight of 25 points; each `Application` belonging to this applicant whose `status` is `ABANDONED` contributes a weight of 15 points; and each `OfficeAction` whose owning `Application` belongs to this applicant and whose `status` is `PENDING` contributes a weight of 5 points. The weighted sum is rounded half-up to an integer and then clamped to the interval from 0 to 100 inclusive — even a portfolio with many lapses can never report a score above 100. When the resulting score is 75 or higher, the applicant's `status` is automatically flipped to `SUSPENDED`; the same flip is also evaluated whenever the applicant is read. A `SUSPENDED` applicant retains read access to their own resources but every write action attempted by that applicant is rejected with `ERR_APPLICANT_SUSPENDED`, regardless of which workflow they were attempting. Listing applicants is open to the admin and the examiner, with optional filters on `entity_size` and `status`.

### 3.2. Drafting and Filing an Application

An applicant drafts a patent filing by creating an `Application` in the `DRAFT` state. The draft payload carries an `applicant_id` (which must equal the acting `Applicant`'s `id`), an `application_type` chosen from `UTILITY`, `DESIGN`, or `PROVISIONAL`, a free-text `title` describing the invention, a `claim_count`, and an `independent_claim_count`. Continuation filings additionally supply a `parent_application_id` pointing at an existing filing plus a `continuation_type` (`NONE`, `CONTINUATION`, or `CIP`), where the parent reference is null and the continuation type is `NONE` when this is an original (non-continuation) filing. A new draft's `status` defaults to `DRAFT`; the system also writes an audit record with the symbolic `action` `APPLICATION_DRAFTED`. A draft's mutable fields — `title`, `claim_count`, and `independent_claim_count` — can be edited while the application remains in `DRAFT`, optionally guarded by a `version` value; any update attempt after the application has left `DRAFT` is rejected as an invalid state. The original creation timestamp is exposed as `created_at` per §2.4; the moment the filing transitions to `FILED` is captured separately as `filed_at`.

Claim shape is enforced at create time and on every draft update. For a `UTILITY` or `DESIGN` filing, `claim_count` must be at least 1 and `independent_claim_count` must be at least 1 and no greater than `claim_count`; for a `PROVISIONAL` filing, both `claim_count` and `independent_claim_count` must be exactly 0. Any violation of these constraints is reported as `ERR_CLAIM_SHAPE_INVALID`. Continuation filings carry an additional referential check: when a non-null `parent_application_id` is supplied, the referenced parent must exist, must not itself be a `PROVISIONAL`, must currently have a `status` that is one of `FILED`, `UNDER_EXAMINATION`, `OFFICE_ACTION_PENDING`, `ALLOWED`, or `GRANTED`, and the supplied `continuation_type` must be either `CONTINUATION` or `CIP` (with `NONE` permitted only when the parent reference is null). Any violation of the parent-pending constraint is reported as `ERR_PARENT_NOT_PENDING`.

Before the filing can advance from `DRAFT` to `FILED`, the applicant must record at least one `FeeTransaction`. Each fee is created against the application's fee-recording capability by supplying a `fee_category` (one of `FILING`, `EXCESS_CLAIM`, `EXAMINATION`, `ISSUE`, `MAINTENANCE`, `EXTENSION`, `PCT_TRANSMITTAL`, or `PCT_NATIONAL`) and an `amount_cents` value that must match the server-computed amount for that category and the applicant's `entity_size`. For maintenance payments the request additionally references a `maintenance_fee_id`; for office-action extension surcharges it references an `office_action_id`; both fields are otherwise null. The `paid_at` timestamp is set by the server at insertion. A category that is inappropriate for the recording endpoint (for example, submitting a `MAINTENANCE` fee outside the maintenance pay flow) is rejected with `ERR_FEE_CATEGORY_INVALID`, and a category whose amount does not match the scaffold-computed amount is rejected with `ERR_FEE_AMOUNT_MISMATCH`. The fee history is listable per application with the optional `fee_category` filter, and the application's denormalised running total `total_fees_paid_cents` is recomputed against the full fee ledger on every insertion.

The actual transition from `DRAFT` to `FILED` requires that the application's `application_type` is set, that its claim counts satisfy the claim-shape rule above, and that a `FILING`-category fee transaction exists at the application's expected filing amount. Whenever the application is a `UTILITY` or `DESIGN` whose `claim_count` exceeds 20 or whose `independent_claim_count` exceeds 3, an additional `EXCESS_CLAIM`-category fee transaction must be present at the expected excess-claim amount. On a successful transition the server records `filed_at` as the current `SystemClock.now`, recomputes `total_fees_paid_cents`, and writes an `APPLICATION_FILED` audit record. For `PROVISIONAL` filings only, the server also computes `expires_at` as the filing instant plus 365 days at the moment of filing — `PROVISIONAL` applications never proceed to examination or grant; they simply expire one year later.

The filing fee table establishes a base amount per application type — 32000 cents for `UTILITY`, 22000 cents for `DESIGN`, and 30000 cents for `PROVISIONAL` — which is then multiplied by the entity-size multiplier from §2.7 and rounded half-up to integer cents in a single step, producing the exact `amount_cents` that the filing-category fee transaction must carry. The micro-entity reduction is the deepest of the three (one quarter of the large-entity base) and is only available to applicants whose `entity_size` is `MICRO` and who additionally satisfy the income and prior-filings caps; a micro applicant whose declared values exceed the caps is rejected during applicant registration or update, before any filing fee is ever computed.

The excess-claim fee is computed per claim above the published thresholds. The number of excess total claims is the larger of zero and `claim_count` minus 20; the number of excess independent claims is the larger of zero and `independent_claim_count` minus 3. Each excess total claim costs 10001 cents at the large-entity rate; each excess independent claim costs 48003 cents at the large-entity rate. The two components are computed independently in a pinned order: first the excess-total component multiplies the unit price by the count and by the entity multiplier and rounds half-up; then the excess-independent component multiplies the unit price by the count and by the entity multiplier and rounds half-up; and only then are the two rounded integer components summed to produce the required `amount_cents`. The reverse order — summing first and rounding once — is explicitly forbidden because it diverges at odd counts under the half and quarter multipliers. The applicant's `entity_size` at the moment of the file transition is the multiplier source for both components.

### 3.3. Examination, Office Actions, and Responses

Once an application is in `FILED` and is either `UTILITY` or `DESIGN`, an examiner may begin examination, transitioning the application to `UNDER_EXAMINATION`. The transition requires that an `EXAMINATION`-category fee transaction already exists for the application at the scaffold-computed examination amount for the applicant's `entity_size`; otherwise the request is rejected with `ERR_FEE_AMOUNT_MISMATCH`. The examiner cannot begin examination on a `PROVISIONAL` filing — provisional applications never enter examination — and any such attempt is reported as an invalid state. The transition writes an `EXAMINATION_BEGUN` audit row.

While in `UNDER_EXAMINATION` the examiner may issue an Office Action, moving the application to `OFFICE_ACTION_PENDING`. The Office Action payload supplies an `action_type` which is one of `NON_FINAL` or `FINAL`. The server assigns a sequential `action_number` per application starting at 1 and incrementing by 1 for each subsequent Office Action on the same application — listing Office Actions for an application surfaces them in order, with an optional `status` filter. The server stamps the issuance instant as `issued_at`, computes `response_deadline_at` as `issued_at` plus 90 days, computes `extended_deadline_at` as `issued_at` plus 180 days (the six-month statutory maximum with extensions, i.e., the three-month shortened period plus three additional months of extensions), and sets the Office Action's `status` to `PENDING`. An `OFFICE_ACTION_ISSUED` audit row is written.

The applicant responds to an Office Action by filing a `Response`. The response transition requires that the Office Action's `status` is `PENDING`, that the response is filed at a moment when `SystemClock.now` is at or before `extended_deadline_at`, and that — when `SystemClock.now` has already passed `response_deadline_at` — an `EXTENSION`-category fee transaction whose `office_action_id` equals this Office Action's `id` exists at the expected extension amount. A response filed after the extended deadline is rejected with `ERR_OFFICE_ACTION_DEADLINE_PASSED`. On success the server creates a `Response` row whose `office_action_id` points back at the Office Action, copies the Office Action's `application_id` into the `Response.application_id` field, stamps the response instant as `filed_at`, sets the Office Action's `status` to `RESPONDED`, transitions the application from `OFFICE_ACTION_PENDING` back to `UNDER_EXAMINATION`, recomputes `Application.total_fees_paid_cents`, and writes an `OFFICE_ACTION_RESPONDED` audit row.

The Response also records two derived fields: `months_extension`, which is the number of full months the response was filed past the shortened-period deadline, and `extension_fee_cents`, which is the matching scaffold-computed fee at the applicant's entity size. The number of days late is the larger of zero and the count of days between the current clock and `response_deadline_at`; `months_extension` is the days-late count divided by 30 and then rounded up to a whole number. If the result is zero (the response is on or before the shortened deadline), `extension_fee_cents` is exactly zero and no extension transaction is required. If the months-late count exceeds three, the response cannot be accepted at all — the six-month extended deadline has been crossed and the rejection is `ERR_OFFICE_ACTION_DEADLINE_PASSED`. For valid late responses, the base extension fee schedule is 22000 cents for one month late, 64000 cents for two months late, and 148000 cents for three months late; the base is multiplied by the applicant's entity multiplier from §2.7 and rounded half-up to integer cents in a single step. The resulting `amount_cents` is what the extension fee transaction must carry.

If the clock advances past an Office Action's `extended_deadline_at` while that Office Action is still `PENDING`, the deadline sweep described in §2.8 deterministically transitions the Office Action's `status` to `ABANDONED_BY_DEFAULT`, cascades the application to `ABANDONED`, and writes an `APPLICATION_ABANDONED_DEADLINE` audit row. Once an application is `ABANDONED` no further actions are accepted against it.

Once every Office Action for the application has been resolved — that is, no Office Action with `status` `PENDING` remains — an examiner may allow the application, transitioning it from `UNDER_EXAMINATION` to `ALLOWED`. An `APPLICATION_ALLOWED` audit row is written. An applicant may also voluntarily abandon their filing at any time while it is in `FILED`, `UNDER_EXAMINATION`, `OFFICE_ACTION_PENDING`, or `ALLOWED`; the abandonment cascades every `PENDING` Office Action for that application into `ABANDONED_BY_DEFAULT`, deletes every `SCHEDULED` `MaintenanceFee` row that may have been provisioned for the application, and writes an `APPLICATION_ABANDONED_VOLUNTARY` audit row.

### 3.4. Grant, Statutory Term, and Maintenance Schedule

To grant an application, an examiner advances it from `ALLOWED` to `GRANTED`. The transition requires that the application's `application_type` is one of `UTILITY` or `DESIGN` (provisional applications cannot be granted) and that an `ISSUE`-category fee transaction exists at the scaffold-computed issue amount for the applicant's `entity_size`. On a successful grant the server stamps `granted_at` as the current clock, computes the statutory `expires_at`, writes an `APPLICATION_GRANTED` audit row, and — for utility patents only — provisions three `MaintenanceFee` rows representing the three statutory maintenance windows. Design patents have no maintenance and provisional applications never reach grant.

Statutory expiration is computed forward-looking from the relevant anchor: a `PROVISIONAL` expires at `filed_at` plus 365 days; a granted `UTILITY` expires at `granted_at` plus 20 years; a granted `DESIGN` expires at `granted_at` plus 15 years. However, the **effective** expiration may be earlier than the forward-looking statutory term if a maintenance fee has lapsed: when at least one `MaintenanceFee` row for the application has a `status` of `LAPSED`, the effective expiration date is the earliest `grace_period_end_at` among the lapsed maintenance rows, which is necessarily earlier than the forward-looking statutory term. When no maintenance fee has lapsed, the effective expiration is simply the statutory term as defined above. Datetime precision is to the second.

The three maintenance windows for utility patents are anchored at 3.5 years, 7.5 years, and 11.5 years after grant. For each, the server provisions a `MaintenanceFee` row whose `stage` is one of `STAGE_3_5`, `STAGE_7_5`, or `STAGE_11_5`, whose `window_open_at` is the grant instant plus the stage anchor in years minus six months (i.e., the grace window opens half a year before the exact due date), whose `due_at` is the grant instant plus the stage anchor in years exactly (3.5, 7.5, or 11.5 years), whose `grace_period_end_at` is the due date plus 180 days, and whose `status` defaults to `SCHEDULED`. The `required_fee_cents` field is left to be recorded at the moment of payment because the appropriate amount depends on whether the payment lands in the timely window or the grace window. Listing maintenance fees for a granted utility application surfaces these rows in order with an optional `status` filter; a request for the maintenance list against a non-utility or non-granted application is rejected with `ERR_MAINTENANCE_NOT_APPLICABLE`.

### 3.5. Paying Maintenance Fees and Lapse

An applicant pays a maintenance fee by invoking the payment transition on a `SCHEDULED` `MaintenanceFee`, advancing its `status` to `PAID`. The transition requires that the owning application's `status` is currently `GRANTED`, that `SystemClock.now` is at or after `window_open_at` and at or before `grace_period_end_at`, and that a `MAINTENANCE`-category fee transaction whose `maintenance_fee_id` equals this `MaintenanceFee`'s `id` exists at the exact `required_fee_cents` value computed below for the applicant's `entity_size`. A payment that falls outside the maintenance window is rejected with `ERR_MAINTENANCE_WINDOW_CLOSED`. On a successful payment the server records `required_fee_cents` against the maintenance row, recomputes `Application.total_fees_paid_cents`, and writes a `MAINTENANCE_FEE_PAID` audit row.

The maintenance fee amount depends on both the stage and whether the payment lands in the timely portion of the window or the grace portion. The base fee table is 160000 cents for `STAGE_3_5`, 360000 cents for `STAGE_7_5`, and 740000 cents for `STAGE_11_5`. A flat surcharge of 16000 cents applies whenever the current clock is strictly after `due_at` and at or before `grace_period_end_at` — that is, when the payment lands in the late-but-still-curable grace portion of the window. When the payment lands in the timely portion (the clock is at or after `window_open_at` and at or before `due_at`), no surcharge applies. The required amount is computed in a pinned order: first multiply the base fee by the applicant's entity multiplier from §2.7 and round half-up to integer cents; then add the flat surcharge if the grace condition is met. The surcharge itself is not subject to the entity multiplier; it is a flat 16000 cents that is added to the rounded entity-adjusted base. Reversing the order — applying the multiplier to the sum of base and surcharge, or applying the multiplier to the surcharge — is not permitted.

When the clock advances past a `MaintenanceFee`'s `grace_period_end_at` while that row is still `SCHEDULED` and no qualifying `MAINTENANCE`-category fee transaction tied to it has been recorded, the deadline sweep in §2.8 deterministically flips the row's `status` to `LAPSED` and writes a `MAINTENANCE_FEE_LAPSED` audit row. A lapsed maintenance fee in turn drives the owning application to `EXPIRED` via the same sweep, which writes an `APPLICATION_EXPIRED` audit row.

### 3.6. PCT International Phase and National Entry

The applicant may initiate the international (PCT) phase against an existing patent filing, creating a `PCTPhase` row in `INTERNATIONAL` state. PCT initiation is only permitted when the parent application's `application_type` is `UTILITY` and its `status` is one of `FILED`, `UNDER_EXAMINATION`, or `OFFICE_ACTION_PENDING`; design, provisional, allowed, or granted applications cannot be elevated to PCT, and any such attempt is rejected with `ERR_PCT_INELIGIBLE`. On initiation the server stamps `pct_filed_at` as the current clock and copies the parent application's `filed_at` into `priority_date` (so that the priority date is captured at PCT-creation time even if the parent's filing instant is later mutated by reissue or correction). The 30-month national-phase deadline is then computed forward: `national_phase_deadline_at` is `priority_date` plus 30 months. The phase status defaults to `INTERNATIONAL`. The PCT row remains attached to its owning `application_id`.

To enter national phase, the applicant invokes the national-entry transition on the PCT row, advancing its `status` to `NATIONAL_ENTERED`. The transition requires that `SystemClock.now` is at or before `national_phase_deadline_at` and that a `PCT_NATIONAL`-category fee transaction exists at the expected national-entry amount for the applicant's `entity_size`. A national-entry attempt after the 30-month deadline is rejected with `ERR_PCT_DEADLINE_PASSED`. On a successful entry the server stamps `national_entered_at` as the current clock and writes a `PCT_NATIONAL_ENTERED` audit row. When the clock advances past `national_phase_deadline_at` while the PCT row is still `INTERNATIONAL`, the deadline sweep deterministically flips its `status` to `LAPSED` and writes a `PCT_LAPSED` audit row; if the parent application later expires by the same sweep its status field becomes `EXPIRED`. The PCT national-entry base fee is 51000 cents at the large-entity rate; this base is multiplied by the applicant's entity multiplier from §2.7 and rounded half-up to integer cents in a single step.

### 3.7. Audit, Read Access, and Clock Administration

Every state-affecting action — applicant registration, application draft creation, draft fields update, filing, examination begin, Office Action issuance, response filing, allowance, grant, voluntary abandonment, deadline-triggered abandonment, maintenance payment, maintenance lapse, PCT initiation, national entry, PCT lapse, application expiration — writes a single `AuditEvent` row tied to the relevant application. The audit list per application is open to the admin, the examiner, and the owning applicant; it is paginated and immutable.

Read access to single resources is broadly available: applicant, application, Office Action, response (when surfaced through its Office Action context), maintenance fee, and PCT phase detail endpoints are all open to the admin and the examiner and to the owning applicant. Listing endpoints accept the standard pagination parameters plus the filters described per workflow above. The clock itself is readable by every authenticated role and is advanced exclusively by the admin via a payload that supplies the target `to` instant; advancing the clock immediately runs the deadline sweep across Office Actions, maintenance fees, PCT phases, and application terms as described in §2.8.

## 4. Endpoint Definitions

All endpoints are mounted under `/applications`, `/applicants`, `/office-actions`, `/maintenance-fees`, `/pct-phases`, and `/_clock` as listed below. Creation endpoints (those that mint a new resource) return HTTP 201; all other successful endpoints — including state transitions on existing resources — return HTTP 200. Errors follow the priority order in §2.11 and the error envelope in §2.2, with the HTTP status code per §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/applicants` | Create a new applicant. | `USPTOAdmin` |
| GET | `/applicants/{id}` | Get an applicant including the recomputed applicant risk score. | `USPTOAdmin`, `Applicant`, `Examiner` |
| PATCH | `/applicants/{id}` | Update mutable applicant fields. | `USPTOAdmin` |
| GET | `/applicants` | List applicants with optional `entity_size` and `status` filters. | `USPTOAdmin`, `Examiner` |
| POST | `/applications` | Create an application in `DRAFT` state. | `Applicant` |
| GET | `/applications/{id}` | Get a single application. | `Applicant`, `Examiner`, `USPTOAdmin` |
| PATCH | `/applications/{id}` | Update mutable application fields while in `DRAFT`. | `Applicant` |
| GET | `/applications` | List applications with optional `applicant_id`, `application_type`, and `status` filters. | `Applicant`, `Examiner`, `USPTOAdmin` |
| POST | `/applications/{id}/fees` | Record a `FeeTransaction` for an application. | `Applicant` |
| GET | `/applications/{id}/fees` | List fee transactions for an application with optional `fee_category` filter. | `Applicant`, `Examiner`, `USPTOAdmin` |
| POST | `/applications/{id}/file` | Transition the application from `DRAFT` to `FILED`. | `Applicant` |
| POST | `/applications/{id}/begin-examination` | Transition the application from `FILED` to `UNDER_EXAMINATION`. | `Examiner` |
| POST | `/applications/{id}/office-actions` | Issue a new Office Action and transition the application from `UNDER_EXAMINATION` to `OFFICE_ACTION_PENDING`. | `Examiner` |
| GET | `/applications/{id}/office-actions` | List Office Actions for an application with optional `status` filter. | `Applicant`, `Examiner`, `USPTOAdmin` |
| POST | `/applications/{id}/allow` | Transition the application from `UNDER_EXAMINATION` to `ALLOWED`. | `Examiner` |
| POST | `/applications/{id}/grant` | Transition the application from `ALLOWED` to `GRANTED`. | `Examiner` |
| POST | `/applications/{id}/abandon` | Voluntarily abandon the application. | `Applicant` |
| POST | `/applications/{id}/pct-phases` | Initiate the PCT international phase. | `Applicant` |
| GET | `/office-actions/{id}` | Get a single Office Action. | `Applicant`, `Examiner`, `USPTOAdmin` |
| POST | `/office-actions/{id}/responses` | File a response to an Office Action. | `Applicant` |
| GET | `/applications/{id}/maintenance-fees` | List maintenance fees for a granted utility application with optional `status` filter. | `Applicant`, `Examiner`, `USPTOAdmin` |
| GET | `/maintenance-fees/{id}` | Get a single maintenance fee. | `Applicant`, `Examiner`, `USPTOAdmin` |
| POST | `/maintenance-fees/{id}/pay` | Pay a maintenance fee, transitioning it from `SCHEDULED` to `PAID`. | `Applicant` |
| GET | `/pct-phases/{id}` | Get a single PCT phase. | `Applicant`, `Examiner`, `USPTOAdmin` |
| POST | `/pct-phases/{id}/enter-national` | Transition the PCT phase from `INTERNATIONAL` to `NATIONAL_ENTERED`. | `Applicant` |
| GET | `/applications/{id}/audit-events` | List immutable audit events for an application. | `USPTOAdmin`, `Examiner`, `Applicant` |
| GET | `/_clock` | Get the current `SystemClock.now`. | `Applicant`, `Examiner`, `USPTOAdmin` |
| POST | `/_clock/advance` | Advance `SystemClock.now` to a supplied `to` instant and run the deadline sweep. | `USPTOAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 |
| `ERR_OFFICE_ACTION_DEADLINE_PASSED` | 409 |
| `ERR_MAINTENANCE_WINDOW_CLOSED` | 409 |
| `ERR_PCT_DEADLINE_PASSED` | 409 |
| `ERR_PARENT_NOT_PENDING` | 422 |
| `ERR_CLAIM_SHAPE_INVALID` | 422 |
| `ERR_MICRO_INELIGIBLE` | 422 |
| `ERR_MAINTENANCE_NOT_APPLICABLE` | 422 |
| `ERR_PCT_INELIGIBLE` | 422 |
| `ERR_FEE_AMOUNT_MISMATCH` | 422 |
| `ERR_FEE_CATEGORY_INVALID` | 422 |
| `ERR_APPLICANT_SUSPENDED` | 403 |
| `ERR_VALIDATION` | 422 |
