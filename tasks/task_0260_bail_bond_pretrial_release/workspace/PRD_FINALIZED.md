# Bail Bond & Pretrial Release API — Product Requirements Document

## 1. Introduction

Pretrial release sits at the intersection of public safety, fiscal accountability, and constitutional liberty. When a court sets bail, a chain of obligations is set in motion: a defendant must be released under enforceable conditions, an agency must put real money or surety at risk, cosigners must stand behind that money, collateral must be held and later returned or seized, and every court appearance must be tracked because a single missed hearing can convert a routine bond into a six-figure judgment. The Bail Bond & Pretrial Release API exists to manage this entire lifecycle as a single auditable system of record, from the moment a bail order is entered through posting, monitoring, forfeiture, recovery, and final settlement.

This system is designed around two non-negotiable concerns. The first is **compliance and audit**: every state change — an activation, a missed appearance, a forfeiture, a remission — must be traceable, and the actors who may perform each step are deliberately segregated so that the agent who profits from posting a bond is never the same person who signs off on releasing the agency's exposure. The second is **ledger reconciliation**: premiums, collateral refunds, forfeiture judgments, and remission credits all flow through an immutable financial ledger, and several derived figures (a defendant's total exposure, an indemnitor's aggregate liability, a bond's held collateral) must be recomputed the instant any contributing fact changes. The remainder of this document specifies the entities, the lifecycles they move through, the calculations that govern money, and the precise validation and authorization contract every client must satisfy.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint. Domain-specific workflow detail lives in Section 3; the financial and lifecycle rules introduced here are reinforced there from the perspective of each business process.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. A request that omits either header, or supplies a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once a caller is authenticated, the system additionally checks that the declared role is permitted to invoke the requested operation; an authenticated caller acting outside their authorized operations is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `BondsAgent`, `Court`, `ComplianceOfficer`, `RecoveryAgent`, and `SystemAdmin`. A `BondsAgent` posts and activates bonds, manages collateral and indemnity agreements, and assigns and operates GPS devices. The `Court` records bail orders, schedules court dates, dispatches notifications, and records appearance outcomes. A `ComplianceOfficer` approves the financially consequential closures — exoneration, reinstatement, judgment, and remission — and is deliberately barred from posting bonds. A `RecoveryAgent` runs the recovery effort, records compliance check-ins, and clears GPS tampers. The `SystemAdmin` role exists solely to drive the test clock.

All five roles carry an **opaque** identity. That is, for every role, `X-User-ID` is an operator identifier that is not tied to any persisted entity; the server may record it where a workflow needs to remember who acted — most importantly, the `X-User-ID` of the `BondsAgent` who activates a bond is retained so it can later be compared against the `X-User-ID` of the `ComplianceOfficer` attempting to exonerate that same bond — but the server never compares `X-User-ID` to any resource's `id`. There is no entity-backed actor in this system; an indemnitor, for example, is a managed `Indemnitor` resource rather than an authenticated caller.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must fall between a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A list request whose `limit` falls outside the inclusive range of 1 through 100, or whose `offset` is below 0, is rejected with `ERR_VALIDATION` (HTTP 422).

Unless an endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Audit Fields

Most resources in the system carry a standard set of system-managed fields. Every such resource receives an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Mutable resources additionally carry an `updated_at` timestamp, refreshed on every change, and a `version`, an integer that begins at its initial value and increments by one on every mutation of the resource. The resources that carry the full `id` / `created_at` / `updated_at` / `version` set are `Defendant`, `BailOrder`, `Bond`, `Indemnitor`, `IndemnityAgreement`, `CollateralItem`, `CourtDate`, `GpsDevice`, and `ForfeitureProceeding`.

Three resources are append-only audit records and carry only an `id` and a `created_at`: a `Notification`, a `CheckIn`, and a `LedgerEntry` have **no** `updated_at` and **no** `version`, because they are never modified after they are written. Recomputation of a derived field — for example refreshing `total_active_exposure_cents` on a `Defendant`, `collateral_held_cents` on a `Bond`, or `total_exposure_cents` on an `Indemnitor` — counts as a mutation of the owning resource: it refreshes that resource's `updated_at` and increments its `version`.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many paths address a resource through a chain of identifiers — a defendant, then a bond, court date, forfeiture proceeding, or device beneath it. The system validates these identifiers left to right and rejects the request at the first identifier that does not resolve to an existing resource, returning `ERR_NOT_FOUND` (HTTP 404). A bond operation nested under a defendant, for instance, fails on the missing defendant before the bond is ever looked up. Separately, when a request body carries a foreign key — an `indemnitor_id`, a `bond_id`, a `device_id`, and the like — and that key points at a resource that does not exist, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404). Body-level foreign-key existence is distinct from path existence and uses its own error.

### 2.6. Request Validation and Ordering of Checks

When several validations could apply to one request, they are evaluated in a fixed priority order so that the rejection a client sees is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then left-to-right path existence (`ERR_NOT_FOUND`), then body foreign-key existence (`ERR_FK_NOT_FOUND`), then structural validity of the body (`ERR_INVALID_REQUEST`, HTTP 400 — a required field absent, a value of the wrong type, or an enum value outside its declared set). Only after these structural gates does the system evaluate domain-specific rules. Among the domain rules, uniqueness conflicts (duplicate case number, duplicate serial) are evaluated, then state-machine legality (`ERR_INVALID_STATE`, HTTP 409 — the target resource is not in a state from which the requested transition is defined), then optimistic-concurrency staleness, and finally the referential, temporal, and fiscal business rules described throughout Section 3. The practical consequence is that a caller never sees a business-rule rejection masking a more fundamental problem: a forfeiture judgment attempted with a stale version against a proceeding in the wrong state surfaces the state error before the staleness check, and a malformed body surfaces `ERR_INVALID_REQUEST` before any business rule runs.

### 2.7. Monetary Precision and Rounding

All monetary amounts in this system are integers denominated in cents; there are no fractional-cent values stored or returned. Where a calculation produces a non-integer intermediate — a premium computed from a basis-point rate, a risk-tier collateral percentage, or a remission percentage of a judgment — the result is rounded to whole cents using the **round half up** method, and rounding is applied once, at the final step of the calculation, never to intermediate band subtotals. Counts and scores (a device's `violation_count`, a check-in's `weight`, a notification's `lead_hours`) are likewise whole integers. The detailed evaluation order for each formula is given in Section 3 alongside the workflow that triggers it.

### 2.8. Cascading State and Derived-Field Reconciliation

A defining characteristic of this domain is that a single action frequently mutates several entities at once, and many fields are derived rather than directly written. When a bond changes its coverage posture, the system recomputes the owning defendant's `total_active_exposure_cents`; when an indemnity agreement changes binding state, it recomputes the owning indemnitor's `total_exposure_cents`; when a collateral item changes status, it recomputes the bond's `collateral_held_cents`. Bond lifecycle changes also bubble upward: a bond's coverage posture drives its `BailOrder.status` and, transitively, the `Defendant.status`. These derived recomputations are immediate and consistent — they happen within the same request that caused them, never on a deferred schedule. Each cascade that touches a resource also refreshes that resource's `updated_at` and increments its `version`, exactly as a direct edit would. The full set of cascades for each operation is enumerated in the workflow subsections; this principle establishes that they are mandatory and synchronous.

### 2.9. Optimistic Concurrency on Forfeiture Judgment

One operation in the system is guarded by optimistic concurrency control: entering a forfeiture judgment against a bond. The judgment request must carry `expected_bond_version`, a non-optional field whose value is the client's last observed `version` of the target `Bond`. Before the judgment is applied, the server compares `expected_bond_version` against the bond's current `version`. If they differ — meaning some other writer has advanced the bond since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects against a stale judgment: if a prior writer already entered judgment against the same bond (liquidating its collateral and calling its indemnity agreements, which legitimately advances `Bond.version`), the second writer's view is stale and its attempt must not overwrite the settled outcome. No other endpoint accepts or requires a version field; only the judgment endpoint participates in this check.

### 2.10. The Financial Ledger

Every financially consequential event on a bond is recorded as an immutable `LedgerEntry` tied to that bond by `bond_id`. Each entry carries an `entry_type` — one of `PREMIUM_COLLECTED`, `COLLATERAL_REFUND`, `FORFEITURE_JUDGMENT`, or `REMISSION_CREDIT` — and a signed `amount_cents` where a positive value is an inflow to the agency and a negative value is an outflow or refund, together with a free-text `memo` that defaults to an empty string. Ledger entries are written as side effects of bond and proceeding transitions, never created directly by a client, and once written they are never altered. The catalogue of which transitions write which entries is given in Section 3.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Defendants and Bail Orders

The lifecycle begins with a `Defendant`. Either a `BondsAgent` or the `Court` registers one by supplying a `full_name`, a `date_of_birth` as an ISO 8601 date in `YYYY-MM-DD` form, and a `phone_e164` contact number in E.164 format that later serves as the destination for court-date notifications. A `risk_tier` may be supplied; when it is omitted it defaults to `MEDIUM`, and it must be one of `LOW`, `MEDIUM`, or `HIGH`. Two fields on a defendant are computed and never accepted from the client: `total_active_exposure_cents`, which begins at 0 and tracks the agency's live exposure to this defendant, and `status`, which begins as `ACTIVE` and is one of `ACTIVE` or `CLEARED`. A defendant remains `ACTIVE` while any of their bonds is in coverage status `ACTIVE` or `FORFEITED`, and becomes `CLEARED` only once every one of their bonds has reached a terminal coverage status (`EXONERATED` or `REVOKED`); this is recomputed by bubble-up whenever a bond's coverage posture changes.

Once a defendant exists, the `Court` records the judicial decision as a `BailOrder`. The order references its defendant through `defendant_id` and carries a `case_number` that must be unique among that defendant's orders — a collision is rejected with `ERR_DUPLICATE_CASE_NUMBER` (HTTP 409). The court-set face value is `bail_amount_cents`, which must be strictly greater than zero. The order declares which posting mechanism the court permits via `bond_type_allowed`, one of `CASH`, `SURETY`, `PR`, or `ANY`. Release conditions are listed in `condition_codes`, an array that defaults to empty and whose members are drawn from the release-condition vocabulary (for example `GPS`, `CURFEW`, `DRUG_TEST`, `NO_CONTACT`). A boolean `gps_required` defaults to false and is set true when the court mandates electronic monitoring. The order's `status` is computed: it begins `OPEN`, becomes `BONDED` once a bond is posted and activated against it, and reaches `RESOLVED` once that bond settles into a terminal coverage status; the permitted values are `OPEN`, `BONDED`, and `RESOLVED`.

### 3.2. Posting and Activating a Bond

A `BondsAgent` posts a `Bond` against a bail order. At posting the agent chooses the `bond_type` — one of `CASH`, `SURETY`, or `PR` — and may negotiate a `premium_rate_bps`, the surety premium rate expressed in basis points where 100 basis points equal one percent. `premium_rate_bps` defaults to 1000 and must be at least 0 and no more than 1500; it is meaningful only for surety bonds and is ignored for cash and PR bonds. The posting must respect the court's permission: the chosen `bond_type` is allowed only when the order's `bond_type_allowed` is `ANY` or exactly equals the chosen type, and a mismatch is rejected with `ERR_BOND_TYPE_NOT_ALLOWED` (HTTP 409). On creation the system records the originating order on the bond as `bail_order_id`, copies the order's face value into the bond's own `bail_amount_cents`, and denormalizes the `defendant_id` onto the bond so exposure can be rolled up without traversing the order. A freshly posted bond enters coverage status `DRAFT`.

A bond carries two independent status dimensions that evolve on their own axes. The first is `coverage_status`, one of `DRAFT`, `ACTIVE`, `FORFEITED`, `EXONERATED`, or `REVOKED`, of which `EXONERATED` and `REVOKED` are terminal. The second is `settlement_status`, one of `UNSETTLED`, `PREMIUM_COLLECTED`, `COLLATERAL_REFUNDED`, or `JUDGMENT_ENTERED`, which begins `UNSETTLED` and advances independently as money moves. Several monetary fields on the bond are computed rather than supplied: `premium_cents` (the surety premium, 0 for cash and PR), `premium_earned_cents` (the portion of premium recognized as earned, beginning at 0), `required_collateral_cents` (the collateral the agent must hold before activation, 0 for PR), and `collateral_held_cents` (the live sum of held collateral, beginning at 0). The bond also carries `posted_at`, a system timestamp that is null until the bond is activated.

The pivotal transition is activation by the posting `BondsAgent`, which advances the bond `DRAFT → ACTIVE`. Activation is permitted only when the bond is currently `DRAFT`; an attempt from any other coverage status is rejected with `ERR_INVALID_STATE`. The court's permitted-type rule is re-affirmed at activation (the order's `bond_type_allowed` must be `ANY` or equal the bond's `bond_type`). Two fiscal preconditions then apply. For a surety bond, the sum of `liability_share_cents` across the bond's pending indemnity agreements must be at least the bond's `bail_amount_cents` — full coverage — and a shortfall is rejected with `ERR_INSUFFICIENT_INDEMNITY` (HTTP 409). For surety and cash bonds alike, `collateral_held_cents` must be at least `required_collateral_cents`, and a shortfall is rejected with `ERR_INSUFFICIENT_COLLATERAL` (HTTP 409); a PR bond requires no collateral and so clears this gate trivially with a requirement of 0.

The two computed money figures on the bond are derived as follows. The required collateral depends on the bond type and the defendant's risk tier. A PR bond requires no collateral, so `required_collateral_cents` is 0. A cash bond must be fully secured, so `required_collateral_cents` equals the bond's full `bail_amount_cents`. A surety bond requires a percentage of face value that rises with risk: the face value is multiplied by 10 percent for a `LOW`-tier defendant, 25 percent for a `MEDIUM`-tier defendant, and 50 percent for a `HIGH`-tier defendant, and the product is rounded half up to whole cents.

The surety premium is priced in marginal bands of face value, never as a single flat rate. The face value (`bail_amount_cents`) is sliced into three bands: the first band is the portion up to 1,000,000 cents, the second band is the portion above 1,000,000 cents and up to 5,000,000 cents (that is, at most 4,000,000 cents wide), and the third band is the portion above 5,000,000 cents. Each band is priced at its own effective rate, which is the greater of the negotiated `premium_rate_bps` and that band's statutory floor — a floor of 1000 basis points on the first band, 800 basis points on the second, and 600 basis points on the third. The premium before the minimum is the sum across the three bands of each band's face amount multiplied by its effective basis-point rate, that total divided by 10,000; the three bands are summed as exact integer products before the single division, and the result is rounded half up to whole cents at that final step only. The bond's `premium_cents` is then the greater of that rounded figure and a non-refundable minimum premium of 10,000 cents. For cash and PR bonds, `premium_cents` is 0 and no premium is charged.

When activation succeeds, a dense cascade of side effects fires within the one request. The system stamps `posted_at` to the current system clock, recomputes `premium_cents` and `required_collateral_cents`, and sets `settlement_status` to `PREMIUM_COLLECTED`. For a surety bond it appends a ledger entry of type `PREMIUM_COLLECTED` whose `amount_cents` equals the positive premium just computed. Every pending indemnity agreement on the bond transitions to `BINDING`, and each affected indemnitor's `total_exposure_cents` is recomputed. The owning `BailOrder.status` is set to `BONDED` by bubble-up, and the defendant's `total_active_exposure_cents` is recomputed to reflect the newly active bond.

A `BondsAgent` may instead abandon a bond that has not yet activated. Revoking a `DRAFT` bond advances it `DRAFT → REVOKED`; revocation is defined only from `DRAFT`, and an attempt from any other status is rejected with `ERR_INVALID_STATE`. Revocation discharges every pending indemnity agreement on the bond and releases every held collateral item, but writes **no** ledger entry — nothing was ever collected or earned, so there is nothing to refund. Because `REVOKED` is terminal, the bond's bail order and defendant statuses bubble up accordingly (an order whose only bond is revoked becomes `RESOLVED`, and a defendant all of whose bonds are terminal becomes `CLEARED`).

### 3.3. Indemnitors, Indemnity Agreements, and Credit Exposure

An `Indemnitor` is the cosigner standing behind a bond. A `BondsAgent` registers one with a `full_name`, a `phone_e164`, and a `credit_limit_cents` that must be strictly greater than zero and caps the aggregate liability this cosigner may guarantee across all bonds. The indemnitor also carries a computed `total_exposure_cents`, beginning at 0, which is the sum of `liability_share_cents` over this indemnitor's agreements whose status is `BINDING` — pending and discharged agreements do not count toward live exposure.

To bind a cosigner to a specific bond, a `BondsAgent` attaches an `IndemnityAgreement` to a draft bond. The agreement references the bond and the cosigner through `bond_id` and `indemnitor_id`, and declares the `liability_share_cents` this cosigner is liable for, which must be strictly greater than zero. The agreement's `status` is computed and is one of `PENDING`, `BINDING`, `DISCHARGED`, or `CALLED`; it is created `PENDING`. Attaching an agreement must not push this indemnitor's exposure over their limit: if the new share, added to the indemnitor's existing binding-and-pending exposure, would exceed `credit_limit_cents`, the attachment is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 409).

The agreement's later life is driven entirely by its bond's transitions rather than by direct edits. When the bond activates, every `PENDING` agreement on it becomes `BINDING`, lifting the indemnitor's exposure by that agreement's share. When the bond is exonerated, every `BINDING` agreement becomes `DISCHARGED`, and the indemnitor's `total_exposure_cents` drops by that agreement's `liability_share_cents`. When the bond was merely a draft and is revoked, its `PENDING` agreements become `DISCHARGED` with no exposure change, since they were never binding. And when a forfeiture judgment is entered, every `BINDING` agreement becomes `CALLED` — the agency is collecting against the cosigner — and the indemnitor's exposure again drops by that agreement's share. The four destinations of an agreement form two forks: a `PENDING` agreement goes either to `BINDING` (activation) or `DISCHARGED` (revoke), and a `BINDING` agreement goes either to `DISCHARGED` (exoneration) or `CALLED` (judgment).

### 3.4. Collateral: Holding, Releasing, and Liquidating

Collateral secures a bond against loss. A `BondsAgent` pledges a `CollateralItem` against a draft bond, naming the bond via `bond_id`, the `kind` (one of `CASH`, `PROPERTY_LIEN`, or `VEHICLE_TITLE`), and the appraised `pledged_value_cents`, which must be strictly greater than zero. An item's `status` is computed and is one of `HELD`, `RELEASED`, or `LIQUIDATED`; it is created `HELD`. Pledging an item recomputes the bond's `collateral_held_cents`, which at all times equals the sum of `pledged_value_cents` over the bond's items whose status is `HELD`.

Collateral status is never edited directly — creation is the only direct write, and every status change thereafter is a cascade from a bond or proceeding transition. On exoneration, every `HELD` item on the bond transitions to `RELEASED`, which drives `collateral_held_cents` back down to 0. Each release records a refund to the pledgor: the refund for an item is its `pledged_value_cents` reduced by a flat processing fee the agency retains, which is 25 dollars (2,500 cents) per item, and the result is floored at zero so a small pledge never produces a negative refund. The corresponding ledger entry is of type `COLLATERAL_REFUND` with an `amount_cents` equal to the **negative** of that per-item refund, reflecting the outflow. By contrast, when a draft bond is revoked its `HELD` items also move to `RELEASED`, but because nothing was ever earned, no ledger entry is written for those releases.

A darker path awaits collateral on a forfeited bond that proceeds to judgment. When judgment is entered, every `HELD` item on the bond transitions to `LIQUIDATED`, the bond's `collateral_held_cents` is driven to 0, and each liquidation appends a ledger entry of type `FORFEITURE_JUDGMENT` whose `amount_cents` equals the item's full `pledged_value_cents` as a positive inflow — the agency has seized the pledge rather than returned it.

### 3.5. The Court-Date Docket and Appearance Outcomes

The `Court` schedules a `CourtDate` against a bond, identifying the bond by `bond_id` and supplying a `scheduled_utc` start instant that must lie in the future relative to the system clock at creation. The hearing occupies a closed interval that begins at `scheduled_utc` and runs for `duration_minutes`, which defaults to 60 and must be strictly greater than zero. The `hearing_type` defaults to `ARRAIGNMENT` and is one of `ARRAIGNMENT`, `PRETRIAL`, `TRIAL`, or `SENTENCING`. A court date's `status` is computed and is one of `SCHEDULED`, `NOTIFIED`, `APPEARED`, `FAILED_TO_APPEAR`, or `CONTINUED`, beginning `SCHEDULED`; it also carries a system field `notified_at` that is null until a notification is dispatched. Of these outcomes, `APPEARED` and `CONTINUED` are terminal appearance results, while `FAILED_TO_APPEAR` is terminal for the appearance but additionally triggers a forfeiture cascade onto the bond.

A new hearing must not collide with another live hearing on the same bond's docket. The system considers existing hearings on that bond whose status is `SCHEDULED` or `NOTIFIED`, each occupying its own closed interval from its `scheduled_utc` for its `duration_minutes`. Before testing for collision, each existing interval is inflated by a mandatory inter-hearing buffer of 30 minutes on **both** ends. The new hearing collides if its start is at or before the buffered end of an existing hearing and the buffered start of that existing hearing is at or before the new hearing's end. Because the intervals are closed and the comparison is inclusive, two hearings that merely touch at the buffer boundary are treated as colliding — adjacency at the boundary is a collision, not a clean fit. A collision is rejected with `ERR_DOCKET_OVERLAP` (HTTP 409).

Dispatching a notification is the `Court`'s reminder action and advances the date `SCHEDULED → NOTIFIED`. It is permitted only while the court date is `SCHEDULED` and the system clock is strictly before the hearing's `scheduled_utc`; an attempt at or after the scheduled instant is a timing violation, rejected with `ERR_TIMING_VIOLATION` (HTTP 409), and the same error guards the failure-to-appear action described below. Dispatch creates a `Notification` record and stamps the court date's `notified_at` to the current clock. A `Notification` references its court date through `court_date_id`, carries a `channel` (defaulting to `SMS`, one of `SMS`, `VOICE`, or `EMAIL`), copies the defendant's `phone_e164` into its `destination`, and records a computed `lead_hours`: the whole number of hours between the moment of dispatch and the hearing's `scheduled_utc`, taken as the elapsed seconds divided by 3,600 and rounded down to a whole number.

Three outcomes close a hearing. Recording an appearance advances the date to `APPEARED` and is allowed when the date is `SCHEDULED` or `NOTIFIED`, with no financial side effects. Continuing a hearing advances it to `CONTINUED` from `SCHEDULED` or `NOTIFIED`, again with no financial side effects, and a fresh court date may then be scheduled for the new date. Recording a failure to appear advances the date to `FAILED_TO_APPEAR`; this is allowed when the date is `SCHEDULED` or `NOTIFIED`, but only when the system clock is at or after the hearing's `scheduled_utc` (an earlier attempt is the same `ERR_TIMING_VIOLATION`), and only when the linked bond is currently in coverage status `ACTIVE`. A failure to appear cascades directly into forfeiture, described next.

### 3.6. Forfeiture, Recovery, Reinstatement, and Judgment

A recorded failure to appear drives the linked bond `ACTIVE → FORFEITED` in the same request, provided the bond is currently `ACTIVE`. The cascade creates a `ForfeitureProceeding` referencing the bond through `bond_id` and the triggering hearing through `trigger_court_date_id`. The proceeding stamps `forfeited_utc` to the system clock at declaration and derives `grace_deadline_utc` as `forfeited_utc` plus a grace period of 30 days; reinstatement and recovery are permitted up to and including that instant, while judgment is permitted only strictly after it. The proceeding's `status` is computed and cyclic, one of `FORFEITED`, `RECOVERY_OPEN`, `REINSTATED`, `JUDGMENT`, or `REMITTED`, of which `REINSTATED` and `REMITTED` are terminal; it begins `FORFEITED`. It also carries a `judgment_amount_cents` field, beginning at 0, that is set only when judgment is entered. Because a forfeited bond remains a live exposure to the agency, recording the failure to appear also recomputes the defendant's `total_active_exposure_cents`, which deliberately keeps both `ACTIVE` and `FORFEITED` bonds in the exposure set.

A `RecoveryAgent` opens the recovery effort, advancing the proceeding `FORFEITED → RECOVERY_OPEN`. This is allowed only while the proceeding is `FORFEITED` and the system clock is at or before `grace_deadline_utc`; an attempt past the deadline is rejected with `ERR_GRACE_EXPIRED` (HTTP 409). Opening recovery has no financial side effects; it simply marks that an active effort is underway. If recovery succeeds in time, a `ComplianceOfficer` reinstates the bond, advancing the proceeding `RECOVERY_OPEN → REINSTATED` and cascading the bond `FORFEITED → ACTIVE`. Reinstatement requires the proceeding to be `RECOVERY_OPEN`, the bond to be currently `FORFEITED`, and the system clock to be at or before `grace_deadline_utc`; a late attempt is again `ERR_GRACE_EXPIRED`. Reinstatement recomputes the defendant's exposure. Because the proceeding shape is cyclic, a reinstated bond that is `ACTIVE` again can fail to appear at a later hearing, opening a brand-new proceeding and repeating the loop.

If the grace period lapses without a reinstatement, a `ComplianceOfficer` enters judgment, driving the proceeding to `JUDGMENT`. Judgment may be entered from either `FORFEITED` or `RECOVERY_OPEN`, but only when the system clock is strictly after `grace_deadline_utc`; an attempt while still within grace is premature and rejected with `ERR_GRACE_NOT_EXPIRED` (HTTP 409). The judgment request must carry `expected_bond_version` matching the bond's current `version`, failing which it is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.9. Entering judgment leaves the bond's `coverage_status` at `FORFEITED` but sets its `settlement_status` to `JUDGMENT_ENTERED`. It liquidates the bond's held collateral and calls its binding indemnity agreements as detailed in §3.3 and §3.4, recomputing each affected indemnitor's exposure. It records the net judgment amount in `judgment_amount_cents` and appends a summary ledger entry of type `FORFEITURE_JUDGMENT` for that net amount, with `memo` set to `net judgment`. Finally, entering judgment increments the bond's `version` by exactly one in net across the entire operation: although collateral liquidation drives the bond's `collateral_held_cents` to 0, that derived-field recompute does not add a separate bond `version` increment here — all of the bond's own mutations in this one operation (the `collateral_held_cents` recompute and the `settlement_status` write) collapse into a single `version` bump, so the bond advances by exactly one whether or not any collateral was held. This single increment is precisely what makes a second, stale judgment attempt fail the concurrency check.

The net judgment is computed sequentially, not as a single formula. Start from the bond's `bail_amount_cents`. Subtract the total `pledged_value_cents` of the collateral items liquidated in this judgment. Then, and only if the proceeding passed through `RECOVERY_OPEN` on its way to judgment, subtract a flat recovery credit of 500 dollars (50,000 cents) recognizing the good-faith recovery effort; the running figure is floored at zero so the judgment is never negative. A proceeding that went straight from `FORFEITED` to `JUDGMENT` without opening recovery receives no such credit — its judgment is face value minus liquidated collateral, floored at zero. The two paths are otherwise identical in every cascade they fire.

A `ComplianceOfficer` may finally remit part of an entered judgment, advancing the proceeding `JUDGMENT → REMITTED`. Remission is defined only from `JUDGMENT` and requires a `remission_pct` strictly greater than 0 and at most 100; a percentage outside that half-open range is rejected with `ERR_INVALID_REMISSION` (HTTP 400). The remitted amount is the proceeding's recorded `judgment_amount_cents` multiplied by `remission_pct` and divided by 100, rounded half up to whole cents at the end. Remission appends a ledger entry of type `REMISSION_CREDIT` whose `amount_cents` is the negative of that remitted amount, and it changes no collateral or indemnity-agreement states — it is purely a financial credit against the judgment.

### 3.7. Exoneration and Clean Release

The happy ending for a bond is exoneration, in which all appearances have been resolved and the agency stands down its exposure. A `ComplianceOfficer` exonerates a bond, advancing it `ACTIVE → EXONERATED`. Exoneration is defined only from `ACTIVE`. Two further preconditions guard it: no court date on the bond may still be open — that is, none may be in status `SCHEDULED` or `NOTIFIED`, since every appearance must be resolved before release — and, enforcing segregation of duties, the acting `ComplianceOfficer` must not be the same user (`X-User-ID`) who activated the bond as a `BondsAgent`. A self-approval attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Exoneration recognizes the full premium as earned and refunds collateral. The bond's `premium_earned_cents` is set equal to its `premium_cents` — the fully-earned variant, in which the entire premium is recognized regardless of how long the bond was active. This stands in contrast to a bond that was revoked from draft before activation, whose `premium_earned_cents` stays 0 because the premium was never collected (its `settlement_status` never reached `PREMIUM_COLLECTED`) and no premium ledger entry ever existed to recognize. Exoneration sets the bond's `settlement_status` to `COLLATERAL_REFUNDED`, releases every held collateral item with the per-item refund ledger entries described in §3.4, discharges every binding indemnity agreement with the exposure recomputation described in §3.3, and returns any active GPS device on the bond as described in §3.8. Finally it sets the `BailOrder.status` to `RESOLVED` and bubbles up the `Defendant.status`, which becomes `CLEARED` once all of the defendant's bonds are terminal.

### 3.8. GPS Monitoring and Condition Compliance

When the court mandates monitoring, a `GpsDevice` enforces it. A `BondsAgent` registers a device with a `serial_number` that must be globally unique; a duplicate serial is rejected with `ERR_DUPLICATE_SERIAL` (HTTP 409). A device carries an `assigned_bond_id` that is null while unassigned, a computed `violation_count` beginning at 0 that accumulates GPS failures recorded against its bond since activation, and a `status` that is one of `UNASSIGNED`, `ASSIGNED`, `ACTIVE`, `TAMPER`, or `RETURNED`, beginning `UNASSIGNED`, of which `RETURNED` is terminal.

A `BondsAgent` assigns a device to a bond, advancing it `UNASSIGNED → ASSIGNED` and setting `assigned_bond_id`; the bond is named in the request body through `device_id`. Assignment is defined only from `UNASSIGNED`, and it is gated twice. First, the bond's bail order must actually mandate monitoring — its `gps_required` must be true — or the assignment is rejected with `ERR_GPS_NOT_REQUIRED` (HTTP 409). Second, a bond's monitoring slot admits at most one non-returned device: the system counts the devices currently referencing this bond whose status is `ASSIGNED`, `ACTIVE`, or `TAMPER`, and if that count is already at or above the capacity of one, the assignment is rejected with `ERR_DEVICE_SLOT_OCCUPIED` (HTTP 409). This is a pure point-in-time occupancy count with capacity one — there is no buffer and no time arithmetic, distinguishing it from the docket-overlap rule.

A `BondsAgent` then activates an assigned device, advancing it `ASSIGNED → ACTIVE`, which is permitted only when the device is `ASSIGNED` and the bond it monitors is in coverage status `ACTIVE`; from activation onward the device counts violations. A GPS failure flips an active device into a tamper alert: the device advances `ACTIVE → TAMPER` and its `violation_count` increments by one. A `RecoveryAgent` clears the alert, advancing the device `TAMPER → ACTIVE`; clearing a tamper does not reset the counter, so the cumulative violation history is preserved. Returning a device advances it to `RETURNED` and clears `assigned_bond_id`; a return is permitted from `ASSIGNED`, `ACTIVE`, or `TAMPER`, and the same return also happens automatically as a cascade when the monitored bond is exonerated (an active device on an exonerated bond is returned).

Condition compliance is verified through check-ins. A `RecoveryAgent` or a `ComplianceOfficer` records a `CheckIn` against a bond, naming the bond through `bond_id`, the `condition_code` being verified (one of `GPS`, `CURFEW`, `DRUG_TEST`, or `NO_CONTACT`), and the `result` reported by the supervising officer (one of `PASS`, `FAIL`, or `MISSED`). The check-in's `occurred_utc` is stamped from the system clock at creation, and its `weight` — the non-compliance points it contributes — is computed jointly from the result and the condition. A `PASS` contributes a weight of 0. A `MISSED` contributes a weight of 1. A `FAIL` contributes a base weight of 2, plus an additional 3 points when the failing condition is `GPS`, so that a GPS failure carries a weight of 5 while any other failure carries a weight of 2. Beyond its own weight, a `GPS` check-in whose result is `FAIL` is the very event that drives an `ACTIVE` GPS device on that bond into `TAMPER` and increments that device's `violation_count`, as described above.

### 3.9. The Test-Driving Clock

Because so much of this domain turns on time — notification lead, failure-to-appear timing, grace deadlines — the system exposes an administrative clock under the `SystemAdmin` role. This capability pins the logical system clock to a supplied instant, provided in the request body as `to_iso8601`, an ISO 8601 UTC value. Once set, every subsequent read of the system clock returns that fixed instant until the next set. This endpoint exists for deterministic temporal testing and performs no domain side effects; the value it pins is what all of the temporal rules above read as "the system clock."

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify an existing resource — every state transition, every activation, exoneration, judgment, and the like — return `200 OK`. The clock-setting capability also returns `200 OK`. To reconstruct the full request body, side effects, and validation order for any endpoint below, refer to the corresponding workflow narrative in Section 3; the table intentionally lists only the HTTP contract and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/defendants` | Register a defendant | BondsAgent, Court |
| GET | `/defendants/{id}` | Fetch a defendant with computed exposure and status | BondsAgent, Court, ComplianceOfficer, RecoveryAgent |
| GET | `/defendants` | List defendants (paginated) | BondsAgent, Court, ComplianceOfficer, RecoveryAgent |
| POST | `/defendants/{id}/bail-orders` | Record a court-set bail order for a defendant | Court |
| GET | `/defendants/{id}/bail-orders` | List a defendant's bail orders | BondsAgent, Court, ComplianceOfficer, RecoveryAgent |
| GET | `/bail-orders/{id}` | Fetch a bail order | BondsAgent, Court, ComplianceOfficer, RecoveryAgent |
| POST | `/defendants/{id}/bail-orders/{order_id}/bonds` | Post a bond against a bail order | BondsAgent |
| GET | `/bonds/{id}` | Fetch a bond with all computed fields and both status dimensions | BondsAgent, Court, ComplianceOfficer, RecoveryAgent |
| GET | `/bail-orders/{id}/bonds` | List bonds under a bail order | BondsAgent, Court, ComplianceOfficer, RecoveryAgent |
| GET | `/bonds` | List/filter bonds | BondsAgent, Court, ComplianceOfficer, RecoveryAgent |
| POST | `/defendants/{id}/bonds/{bond_id}/activate` | Activate a draft bond | BondsAgent |
| POST | `/defendants/{id}/bonds/{bond_id}/exonerate` | Exonerate an active bond | ComplianceOfficer |
| POST | `/defendants/{id}/bonds/{bond_id}/revoke` | Revoke a draft bond before activation | BondsAgent |
| POST | `/indemnitors` | Register an indemnitor | BondsAgent |
| GET | `/indemnitors/{id}` | Fetch an indemnitor with computed exposure | BondsAgent, ComplianceOfficer |
| POST | `/defendants/{id}/bonds/{bond_id}/indemnity-agreements` | Attach an indemnitor to a draft bond | BondsAgent |
| GET | `/bonds/{id}/indemnity-agreements` | List agreements on a bond | BondsAgent, ComplianceOfficer |
| GET | `/indemnity-agreements/{id}` | Fetch a single indemnity agreement | BondsAgent, ComplianceOfficer |
| GET | `/indemnity-agreements` | Filtered list of indemnity agreements | BondsAgent, ComplianceOfficer |
| POST | `/defendants/{id}/bonds/{bond_id}/collateral` | Pledge a collateral item against a draft bond | BondsAgent |
| GET | `/bonds/{id}/collateral` | List collateral on a bond | BondsAgent, ComplianceOfficer |
| POST | `/defendants/{id}/bonds/{bond_id}/court-dates` | Schedule a court date for a bond | Court |
| GET | `/bonds/{id}/court-dates` | List court dates on a bond | BondsAgent, Court, ComplianceOfficer, RecoveryAgent |
| GET | `/court-dates/{id}` | Fetch a court date | BondsAgent, Court, ComplianceOfficer, RecoveryAgent |
| POST | `/defendants/{id}/court-dates/{court_date_id}/notify` | Dispatch a court-date notification | Court |
| GET | `/court-dates/{id}/notifications` | List notifications for a court date | BondsAgent, Court, ComplianceOfficer |
| POST | `/defendants/{id}/court-dates/{court_date_id}/record-appearance` | Record that the defendant appeared | Court |
| POST | `/defendants/{id}/court-dates/{court_date_id}/record-fta` | Record failure to appear; cascade forfeiture | Court |
| POST | `/defendants/{id}/court-dates/{court_date_id}/continue` | Continue/postpone a court date | Court |
| POST | `/defendants/{id}/check-ins` | Record a condition-compliance check-in | RecoveryAgent, ComplianceOfficer |
| GET | `/bonds/{id}/check-ins` | List check-ins on a bond | BondsAgent, ComplianceOfficer, RecoveryAgent |
| POST | `/gps-devices` | Register a GPS monitoring device | BondsAgent |
| GET | `/gps-devices/{id}` | Fetch a GPS device | BondsAgent, ComplianceOfficer, RecoveryAgent |
| POST | `/defendants/{id}/bonds/{bond_id}/gps/assign` | Assign a GPS device to a bond | BondsAgent |
| GET | `/bonds/{id}/gps-devices` | List GPS devices assigned to a bond | BondsAgent, ComplianceOfficer, RecoveryAgent |
| POST | `/defendants/{id}/gps/{device_id}/activate` | Activate an assigned device | BondsAgent |
| POST | `/defendants/{id}/gps/{device_id}/clear-tamper` | Clear a tamper alert | RecoveryAgent |
| POST | `/defendants/{id}/gps/{device_id}/return` | Return a device | BondsAgent |
| GET | `/forfeitures/{id}` | Fetch a forfeiture proceeding | BondsAgent, ComplianceOfficer, RecoveryAgent |
| GET | `/bonds/{id}/forfeitures` | List proceedings for a bond | BondsAgent, ComplianceOfficer, RecoveryAgent |
| GET | `/court-dates/{id}/forfeitures` | List proceedings triggered by a court date | BondsAgent, ComplianceOfficer, RecoveryAgent |
| POST | `/defendants/{id}/forfeitures/{proceeding_id}/open-recovery` | Open the recovery effort | RecoveryAgent |
| POST | `/defendants/{id}/forfeitures/{proceeding_id}/reinstate` | Reinstate a recovered bond | ComplianceOfficer |
| POST | `/defendants/{id}/forfeitures/{proceeding_id}/enter-judgment` | Enter judgment after the grace period lapses | ComplianceOfficer |
| POST | `/defendants/{id}/forfeitures/{proceeding_id}/remit` | Remit part of an entered judgment | ComplianceOfficer |
| GET | `/bonds/{id}/ledger` | List ledger entries for a bond | BondsAgent, ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Pin the system clock to a fixed instant | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_CASE_NUMBER` | 409 |
| `ERR_DUPLICATE_SERIAL` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BOND_TYPE_NOT_ALLOWED` | 409 |
| `ERR_GPS_NOT_REQUIRED` | 409 |
| `ERR_DOCKET_OVERLAP` | 409 |
| `ERR_DEVICE_SLOT_OCCUPIED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_GRACE_EXPIRED` | 409 |
| `ERR_GRACE_NOT_EXPIRED` | 409 |
| `ERR_TIMING_VIOLATION` | 409 |
| `ERR_INSUFFICIENT_INDEMNITY` | 409 |
| `ERR_INSUFFICIENT_COLLATERAL` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 |
| `ERR_INVALID_REMISSION` | 400 |
| `ERR_VALIDATION` | 422 |
