# Condominium Conversion Offering API — Product Requirements Document

## 1. Introduction

Converting an existing rental building into a condominium regime is one of the most heavily
supervised transactions in real estate. Before a single unit can be sold, a converter must prove
that the building is physically fit for a decades-long ownership horizon, carve the structure into
legally described units and common elements, register a disclosure document with the state, honour
the statutory protections owed to the people already living in the building, fund a reserve account
against the eventual replacement of roofs, elevators and boilers, and satisfy secondary-market
lenders that the finished project will be mortgageable. Today that work is spread across engineering
firms, law offices, escrow companies and regulator inboxes, and the sequencing errors it produces
are expensive: statements go effective before the declaration is recorded, closings fund before
presale thresholds are actually met, and relocation cheques are cut against obligations that were
already reversed.

This document specifies the Condominium Conversion Offering API, a compliance registry that holds a
conversion project and every artefact hanging off it — engineering reports on the remaining useful
life of major components and their independent peer review, the declaration package with its plat
and unit boundary definitions, the nine statutory sections of the public offering statement, tenant
household notices with their right-of-first-refusal offers and relocation assistance, the reserve
funding study and the initial budget with its developer deficit funding, closing batches whose
release is withheld until minimum presale thresholds are met, purchase agreements with their
pre-sale rescission windows, and warranty claims against the common elements. The system does not
merely store these records; it derives them from one another and refuses transitions that would
leave the project internally inconsistent.

Two design commitments shape everything that follows. The first is **segregation of duties**: the
sponsor who authors the disclosure may never bless it, the engineer who files a report may never
peer-review it, and the party who creates a financial obligation may never settle it. The second is
**conservation**: escrow cash, the ten-thousand-basis-point undivided interest in the common
elements, and the relocation obligation owed to tenants are each tracked as a quantity that must
reconcile to zero drift after every single request, so that a compensating pair of actions returns
the project to exactly the picture it presented before.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across every endpoint of the API: how
callers identify themselves, what a response looks like, how lists are paged, how time is measured,
how records are versioned, and in what order a request is rejected. Nothing in this section is
domain-specific to one workflow; the workflows themselves are described in section 3, and they
inherit everything stated here without restating it.

### 2.1. Acting Identity and Role-Based Access Control

Every request to this API is authenticated by two mandatory HTTP headers. `X-User-ID` carries the
identifier of the acting party, and `X-User-Role` declares the capacity in which that party is
acting. Nine roles are recognised, and their names are spelled exactly as follows:
`ConverterSponsor`, `LicensedEngineer`, `PeerReviewEngineer`, `StateRegulator`, `EscrowAgent`,
`LenderUnderwriter`, `PlatformAdmin`, `TenantOccupant`, and `Purchaser`. If either header is absent
or empty, or if the value of `X-User-Role` is not one of those nine names, the request is rejected
with `ERR_MISSING_AUTH_HEADERS` and HTTP 401. If the headers are well-formed but the acting role is
not among the roles the target endpoint admits, the request is rejected with
`ERR_ROLE_NOT_PERMITTED` and HTTP 403.

A brief word on who these parties are. The `ConverterSponsor` is the declarant: it owns the project
record, the declaration and plat, the unit definitions, tenant notices, the reserve study and
initial budget, the offering statement content, the closing batch structure and warranty
remediation. The `LicensedEngineer` is the engineer of record who inspects the building, files the
report on remaining useful life, and edits component data. The `PeerReviewEngineer` is the
independent reviewer that verifies individual components and accepts or rejects the report; it holds
the only path to component verification. The `StateRegulator` is the registration authority and is
solely responsible for declaring a public offering statement effective. The `EscrowAgent` is the
independent escrow holder and is the only party that may move money — earnest money deposits,
relocation disbursements, batch release and closing disbursement. The `LenderUnderwriter` is a
secondary-market underwriter and is strictly read-only: it may inspect every ratio and verdict but
may not mutate any resource. The `PlatformAdmin` operates the registry platform, holds the clock and
the project-level operational knobs and may run the posture sweep, but is deliberately excluded from
every substantive compliance decision. The `TenantOccupant` is an existing tenant household of the
building, and the `Purchaser` is a unit buyer.

Seven of the nine roles are **opaque operator identities**. When `X-User-Role` is
`ConverterSponsor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity;
the server may record it (for example, as `sponsor_user_id` on a `ConversionProject`) but does not
compare it to any entity's `id`. When `X-User-Role` is `LicensedEngineer`, `X-User-ID` is an opaque
operator identifier not tied to any persisted entity; the server may record it (for example, as
`submitted_by_user_id` on an `EngineeringReport`, which the submit transition writes from the
header) but does not compare it to any entity's `id`. When `X-User-Role` is `PeerReviewEngineer`,
`X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record
it (for example, as `reviewed_by_user_id` on an `EngineeringReport`, which the peer-review decision
writes from the header) but does not compare it to any entity's `id`. When `X-User-Role` is
`StateRegulator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the
server may record it (for example, as `attested_by_user_id` on a `POSSection`) but does not compare
it to any entity's `id`. When `X-User-Role` is `EscrowAgent`, `X-User-ID` is an opaque operator
identifier not tied to any persisted entity; the server may record it but does not compare it to any
entity's `id`. When `X-User-Role` is `LenderUnderwriter`, `X-User-ID` is an opaque operator
identifier not tied to any persisted entity; the server may record it but does not compare it to any
entity's `id`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier
not tied to any persisted entity; the server may record it but does not compare it to any entity's
`id`.

The remaining two roles are **entity-backed**, and for them `X-User-ID` is not an operator label but
a primary key. When `X-User-Role` is `TenantOccupant`, `X-User-ID` is the `id` of the acting
`TenantHousehold`; ownership checks on any resource that references a `TenantHousehold` compare the
resource's foreign-key field to `X-User-ID`, so a household may answer its own right-of-first-refusal
offer and read its own record but nothing belonging to another household. When `X-User-Role` is
`Purchaser`, `X-User-ID` is the `id` of the acting `PurchaseAgreement`; ownership checks on any
resource that references a `PurchaseAgreement` compare the resource's foreign-key field to
`X-User-ID`, so a purchaser may rescind its own contract but not another purchaser's. A request from
an entity-backed role acting on a resource it is not bound to — a `TenantOccupant` whose `X-User-ID`
is not the `id` of the household named in the path, or a `Purchaser` whose `X-User-ID` is not the
`id` of the agreement named in the path — is rejected with `ERR_IDENTITY_MISMATCH` and HTTP 403.

Segregation of duties is enforced at the same tier. When a peer-review decision is filed on an
engineering report, the acting `X-User-ID` must differ from the value stored in the report's
`submitted_by_user_id`; an engineer attempting to review its own submission is rejected with
`ERR_SEGREGATION_OF_DUTIES` and HTTP 403.

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

### 2.3. Pagination of Registry Collections

Every list endpoint in the registry is paginated by the same two query parameters. `limit` controls
the page size: it defaults to 10 when omitted, its minimum accepted value is 1 and its maximum
accepted value is 100. `offset` controls the starting position within the ordered result set: it
defaults to 0 when omitted and must not be negative. A `limit` outside the inclusive range from 1 to
100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` and HTTP 422; neither value
is silently clamped.

Unless a specific list endpoint states otherwise, results are ordered by `created_at` ascending, so
that paging through a collection walks the registry in the order its records were minted. The
pagination state travels in the response envelope's `meta` object rather than in the payload: list
responses carry `limit` and `offset` echoing the effective values applied to the query,
`total_count` giving the number of records matching the filter across all pages, and `has_more`
indicating whether any record remains beyond the current page. Single-resource responses omit all
four.

### 2.4. The Logical Registry Clock

Condominium conversion is a calendar-driven process — notice periods, rescission windows, warranty
horizons and remediation schedules are all measured in elapsed time — so this API deliberately does
not read the host machine's wall clock. Instead the server maintains a single **logical clock**
whose value is the API's only notion of "now". At server startup the logical clock reads exactly
`2026-08-01T00:00:00Z`, and it holds that value until it is explicitly moved; it never falls back to
real wall-clock time, at startup or afterwards.

An administrative capability sets the logical clock to a supplied instant, carried in the request as
`current_utc`. A second, read-only capability returns the clock's current instant, and every role may
read it. Moving the clock is not itself an event: advancing time fires no state transition on its
own. Sweeps that react to elapsed time — tenant vacate deadlines coming due, right-of-first-refusal
offers lapsing, remediated warranty claims closing out — are fired explicitly by a posture
recalculation request, described in section 3.

Every temporal comparison in this specification is made against the logical clock and never against
any other time source. That includes each tenant household's notice period and `vacate_deadline_at`,
the right-of-first-refusal expiry at `rofr_expires_at`, each purchase agreement's pre-sale rescission
deadline at `rescission_deadline_at`, the common-element warranty expiry at `warranty_expires_at`,
the half-open closing-batch windows, the closed warranty remediation windows, the remaining
useful-life horizon used by the reserve funding study, and every `*_at` instant the system stamps
onto a record as a side effect of a transition. Where a workflow below says a deadline "has elapsed",
it means the logical clock has reached or passed that instant; boundary inclusivity is stated
individually for each such comparison in section 3, because the API does not apply a uniform
convention.

### 2.5. Registry Record Identity, Revision Counters and Cascade Propagation

Fourteen resource types make up the conversion registry: `ConversionProject`, `EngineeringReport`,
`MajorComponent`, `SuitabilityAssessment`, `DeclarationPackage`, `Unit`, `PublicOfferingStatement`,
`POSSection`, `TenantHousehold`, `ReserveStudy`, `InitialBudget`, `ClosingBatch`,
`PurchaseAgreement`, and `WarrantyClaim`. Every one of the fourteen carries the same four common
properties in addition to its own domain fields, and none of the fourteen omits any of them.

`id` is a server-minted UUID. The client never supplies it, and it carries no type prefix — the
identifier of a closing batch and the identifier of a warranty claim are indistinguishable by shape,
so callers must not attempt to infer a resource's type from its identifier. `created_at` is the ISO
8601 UTC instant at which the record was minted, formatted with exactly three fractional digits.
`updated_at` is the ISO 8601 UTC instant of the record's most recent mutation, in the same format;
on a freshly created record it equals `created_at`. `version` is an integer revision counter that
starts at 1 when the record is created and is incremented by exactly one on every mutation of that
record. Resource creation returns HTTP 201; a request that modifies an existing resource returns
HTTP 200.

The crucial point about `updated_at` and `version` is that they are per-record, not per-request. This
registry is a graph rather than an ownership tree, and a single accepted request routinely rewrites
several records at once: a peer-review acceptance rewrites the engineering report and re-derives the
project's gating posture, a unit withdrawal reallocates the percentage interest of every sibling unit
in the declaration package and re-derives the initial budget's assessment income, an escrow deposit
rewrites the purchase agreement and re-runs the project's escrow reconciliation, and a threshold
evaluation rewrites the closing batch. **Each entity touched by such a cascade has its own
`updated_at` refreshed to the current logical clock reading and its own `version` incremented by
one**, whether it was the resource named in the request path or a record reached indirectly through
a cascaded side effect. Cascades are applied immediately and synchronously within the request that
triggers them; there is no deferred or eventually-consistent settlement, so a read issued after a
successful write always observes the full consequences of that write.

Because cascaded bumps are indistinguishable from direct ones, a client holding a `version` it read
before some unrelated operation cascaded into the same record is holding a stale value. That is the
whole reason the optimistic-concurrency guards of section 2.7 exist, and it is why the cascade rules
in section 3 are stated exhaustively rather than left as an implementation detail.

### 2.6. Path Resolution and the Order of Rejection

A request that is wrong in several ways at once must fail in a predictable way, because callers build
retry logic on the error they receive. This API therefore evaluates every request through a single
fixed ladder of checks and returns the error belonging to the **first** rung that fails; later rungs
are never evaluated once a rung has rejected. The ladder is global — it is not restated per endpoint —
and it runs as follows.

**Rung 1 — authentication.** Both `X-User-ID` and `X-User-Role` must be present and non-empty, and
`X-User-Role` must name one of the nine roles. Otherwise `ERR_MISSING_AUTH_HEADERS`, HTTP 401.

**Rung 2 — authorization.** The acting role must appear in the target operation's permitted role
list, or the request fails with `ERR_ROLE_NOT_PERMITTED`, HTTP 403. Immediately after that, an
entity-backed role's ownership binding is checked — a right-of-first-refusal response requires the
acting `X-User-ID` to be the `id` of the household in the path, and a rescission requires the acting
`X-User-ID` to be the `id` of the agreement in the path — failing which the answer is
`ERR_IDENTITY_MISMATCH`, HTTP 403. Last on this rung, a peer-review decision whose acting `X-User-ID`
equals the report's `submitted_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`, HTTP 403.

**Rung 3 — existence, resolved strictly left to right along the URL.** Path segments are resolved in
the order they appear, and the first segment that fails to resolve determines the error; a request
naming a non-existent project inside a path that also names a non-existent unit reports the project
failure and stops. Within this rung the resolution order across resource families is: the conversion
project identified in any path containing a project segment, reported as `ERR_PROJECT_NOT_FOUND`;
then engineering artefacts — an engineering report, major component or suitability assessment —
reported as `ERR_ENGINEERING_ARTIFACT_NOT_FOUND`; then declaration artefacts, meaning a declaration
package or a unit, reported as `ERR_DECLARATION_ARTIFACT_NOT_FOUND`; then disclosure artefacts,
meaning a public offering statement, reported as `ERR_DISCLOSURE_ARTIFACT_NOT_FOUND`, which is also
the error when a section is addressed by a `section_code` that is not one of the nine statutory
section codes; then a tenant household, reported as `ERR_TENANT_NOT_FOUND`; then financial artefacts,
meaning a reserve study or an initial budget, reported as `ERR_FINANCIAL_ARTIFACT_NOT_FOUND`; then
sales artefacts, meaning a purchase agreement or a closing batch, reported as
`ERR_SALES_ARTIFACT_NOT_FOUND`; and finally a warranty claim, reported as `ERR_CLAIM_NOT_FOUND`.
Every one of these is HTTP 404. Identifiers supplied in a **request body** rather than in the path
are resolved on this same rung and under the same family-specific error: `engineering_report_id` and
`major_component_id` under `ERR_ENGINEERING_ARTIFACT_NOT_FOUND`; `declaration_package_id`,
`occupied_unit_id`, `unit_id` and `reported_by_unit_id` under `ERR_DECLARATION_ARTIFACT_NOT_FOUND`;
`tenant_household_id`, when supplied as a non-null value, under `ERR_TENANT_NOT_FOUND`;
`reserve_study_id` and `initial_budget_id` under `ERR_FINANCIAL_ARTIFACT_NOT_FOUND`; and
`purchase_agreement_id` under `ERR_SALES_ARTIFACT_NOT_FOUND`.

**Rung 4 — project scope.** Once every identifier resolves, the referenced records must all belong
to the same conversion project as the path resource. A reserve study, initial budget, offering
statement, tenant household, warranty claim, unit, purchase agreement or closing batch drawn from a
different project — that is, whose project association differs from the project of the path resource,
including a major component reached through a report belonging to another project — is rejected with
`ERR_PROJECT_SCOPE_MISMATCH`, HTTP 409.

**Rung 5 — request shape.** Required body fields must be present, types must match, enum values must
be members of their declared set, integers must fall inside their declared ranges, and datetimes must
be ISO 8601 UTC; a violation is `ERR_INVALID_REQUEST`, HTTP 422. Pagination arguments are validated
here too, yielding `ERR_INVALID_PAGINATION`, HTTP 422. Uniqueness is the last shape concern:
a duplicate on any of the registry's natural keys is rejected with `ERR_DUPLICATE_KEY`, HTTP 409.

**Rung 6 — optimistic concurrency.** The four version-guarded writes described in section 2.7 are
checked here, before any state precondition, yielding `ERR_STALE_UNIT_VERSION`,
`ERR_STALE_REPORT_VERSION`, `ERR_STALE_PROJECT_VERSION` or `ERR_STALE_BATCH_VERSION` as appropriate,
each with HTTP 412.

**Rung 7 — posture gates and state preconditions.** The project's derived posture is consulted
first: a project whose posture is `FROZEN` rejects writes outside its pinned exemption list with
`ERR_PROJECT_FROZEN`, and a batch release attempted on a project whose posture is `RESTRICTED` rather
than `OPEN` is rejected with `ERR_PROJECT_RESTRICTED`. Next the target record's own state must be a
declared source state for the requested transition; if it is not — including a record already in a
terminal state and a trigger replayed against a record that has already moved on — the answer is
`ERR_INVALID_STATE_TRANSITION`. The remaining preconditions of this rung are the cross-record
readiness gates: `ERR_BATCH_NOT_RELEASED`, `ERR_POS_NOT_EFFECTIVE`, `ERR_DECLARATION_NOT_RECORDED`,
`ERR_RESERVE_STUDY_NOT_ADOPTED` and `ERR_POS_NOT_DELIVERED`. All of the errors on this rung carry
HTTP 409.

**Rung 8 — business rules, in domain order.** Only after everything above has passed are the
substantive conversion rules evaluated, and they are evaluated in this declared order: first
building-safety and disclosure-completeness rules (`ERR_LIFE_SAFETY_COMPONENT_EXPIRED`,
`ERR_SUITABILITY_GATE_FAILED`, `ERR_NO_VERIFIED_COMPONENTS`, `ERR_POS_SECTIONS_INCOMPLETE`); then the
clock-relative rules (`ERR_NOTICE_PERIOD_NOT_ELAPSED`, `ERR_ROFR_WINDOW_EXPIRED`,
`ERR_RESCISSION_PERIOD_OPEN`, `ERR_RESCISSION_PERIOD_CLOSED`, `ERR_WARRANTY_PERIOD_EXPIRED`,
`ERR_BATCH_WINDOW_OVERLAP`, `ERR_REMEDIATION_WINDOW_OVERLAP`,
`ERR_REMEDIATION_CAPACITY_EXCEEDED`); then the remaining referential linkage rules
(`ERR_ROFR_UNIT_NOT_LINKED`, `ERR_AGREEMENT_ALREADY_ASSIGNED`); then the structural constraint rules
(`ERR_PERCENTAGE_INTEREST_NOT_BALANCED`, `ERR_LAST_INCLUDED_UNIT`, `ERR_NO_INCLUDED_UNITS`,
`ERR_CLAIM_REOPEN_LIMIT_REACHED`); and last the fiscal rules (`ERR_ESCROW_AMOUNT_MISMATCH`,
`ERR_ESCROW_NOT_FUNDED`, `ERR_RELOCATION_AMOUNT_MISMATCH`, `ERR_PRESALE_THRESHOLD_NOT_MET`). The
condition that triggers each of these lives with the workflow it guards in section 3, and the HTTP
status of each is listed in section 5.

The practical consequence of the ladder is worth spelling out: a rule that sits low on it can be
masked. A caller who submits a malformed body against a frozen project sees `ERR_INVALID_REQUEST`,
not `ERR_PROJECT_FROZEN`, because request shape is rung 5 and the posture gate is rung 7. Conversely a
stale version is reported in preference to any state or business objection, because optimistic
concurrency sits above both.

### 2.7. Optimistic Concurrency on Shared Parent Records

Four write operations in this registry attach a child record to a parent whose own fields are
rewritten by unrelated activity. In each case the decision the caller is making depends on the
parent's current contents, so the caller must prove it has read the parent as it stands now. This is
expressed as an optimistic-concurrency guard: the request carries the `version` the client last
observed on the parent, and the write proceeds only if that value still equals the parent's current
`version`. These four operations are the only ones that take a version field; every other endpoint in
the API accepts no version input, and supplying one there has no defined meaning.

**Recording a purchase agreement against a unit.** The request must carry
`expected_unit_version`, and it is a required field, not an optional one. Its value must equal the
target `Unit`'s current `version`. A unit whose previous agreement moved to `RESCINDED` or `VOID`
legitimately accepts a fresh agreement, so the operation itself is perfectly valid from the same
observable unit state — the guard exists because the supersede that freed the unit also rewrote its
`sale_status`, its `percentage_interest_bp` and its `unit_annual_assessment_cents`, and a client
holding the earlier `version` has not seen those rewrites. If the supplied value does not match, the
request is rejected with `ERR_STALE_UNIT_VERSION` and HTTP 412.

**Creating a suitability assessment against an engineering report.** The request must carry
`expected_engineering_report_version` as a required field, matching the target `EngineeringReport`'s
current `version`. A new assessment legitimately supersedes the prior effective assessment on the
same report, so the create is valid from the same observable report state; the guard exists because
that supersede also rewrote the project's `suitability_gate` and `suitability_score` off the
superseded row. A mismatch is rejected with `ERR_STALE_REPORT_VERSION` and HTTP 412.

**Creating an initial budget for a conversion project.** The request must carry
`expected_conversion_project_version` as a required field, matching the target `ConversionProject`'s
current `version`. A new budget legitimately supersedes the project's prior `DRAFT` budget, so the
create is valid from the same observable project state; the guard exists because the supersede
re-derives `assessment_income_cents` from the project's current set of `INCLUDED` units, which a
client working from an older `version` has not seen. A mismatch is rejected with
`ERR_STALE_PROJECT_VERSION` and HTTP 412.

**Assigning a purchase agreement to a closing batch.** The request must carry
`expected_closing_batch_version` as a required field, matching the target `ClosingBatch`'s current
`version`. Adding a further agreement to the same batch is legitimate from the same observable batch
state, so this is not a state precondition; the guard exists because each accepted assignment rewrites
the batch's `qualifying_agreement_count` and `presale_pct`, and a client working from an older
`version` would be deciding batch composition from an outdated threshold picture. A mismatch is
rejected with `ERR_STALE_BATCH_VERSION` and HTTP 412.

All four checks are evaluated at rung 6 of the ladder in section 2.6 — after the referenced records
have been resolved and the request body has been validated, but before any posture gate, state
precondition or business rule. A stale version is therefore reported in preference to a state or
business objection that the same request would also have failed.

### 2.8. Cents, Basis Points, Percentages and Day-Multiples: Precision Discipline

Conversion arithmetic mixes four kinds of quantity, and each has its own fixed representation. The
rules below are global; where a specific computation applies rounding at a specific step, that step is
named here and repeated in the workflow narrative, because applying the same rounding at a different
point in the sequence produces a different answer.

**Money is always whole cents.** Every field whose name ends in `_cents` is an integer number of
cents; there are no fractional cents anywhere in the API and no currency is expressed as a decimal.
Where a monetary computation produces a fraction, the default treatment is **round half up** — a
result exactly at the half-cent goes to the larger magnitude. Four places pin something more specific.
In the reserve funding study, per-component amounts are rounded *before* they are summed rather than
after: the fully funded balance contribution of each component is rounded half up, whereas each
component's annual contribution is taken to the **ceiling** — rounded up to the next whole cent
whenever any fraction remains — so the recommended annual contribution is never short by a rounding
artefact. In the initial budget, `management_fee_cents` is rounded half up to whole cents and is
computed exactly once, at the point in the evaluation order where the base expense determines the fee
tier; it is never recomputed against a later subtotal, and every other amount in the budget is already
an integer number of cents. In the per-unit assessment allocation, each unit's annual amount is
rounded half up to whole cents *before* the amounts are summed, and the whole remaining residual is
then applied to exactly one unit, so the allocation reconciles to the target total exactly; each
unit's monthly amount is then rounded half up independently from that already-rounded annual amount,
not from the unrounded share. In the tenant notice and relocation computation, cents are rounded half
up at the base-entitlement step and again at the protected-class uplift step, and at no other step.
Warranty charges are whole cents rounded half up.

**Undivided ownership interest is always whole basis points.** A unit's share of the common elements
is an integer count of basis points, never a percentage with decimals. The allocation across units
**truncates** each raw share rather than rounding it, and then restores the whole truncation residual
so that the set of `INCLUDED` units sums to exactly 10000 basis points. Truncate-then-sweep is the
sanctioned order; rounding each share and patching the difference afterwards is not the same
computation and does not produce the same per-unit values. The reserve study's funding adequacy is
likewise expressed in basis points: `percent_funded_bp` is rounded half up to a whole basis point.

**Ratios exposed to lenders and thresholds are percentages with exactly two decimal places.** The
owner-occupancy, investor-concentration, single-investor and presale percentages are all carried to
two decimal places and rounded half up. Each is computed **once, directly from exact integer counts**,
and never from a previously rounded percentage — chaining one rounded ratio into another is
specifically not the contract. The presale percentage is compared against a batch's minimum threshold
using the rounded two-decimal value, not the unrounded quotient. The building suitability score
follows the same shape: it is a number in the closed range from 0.00 to 100.00 carried to two decimal
places, and the half-up rounding is applied exactly once, to the final scaled result, never to any
intermediate term.

**Derived instants are exact multiples of whole days, and other instants are whole seconds.** Notice
periods, vacate deadlines, right-of-first-refusal expiries and rescission deadlines are all computed
as an exact multiple of 86400 seconds added to their anchor instant. No calendar adjustment, no
month-length adjustment and no business-day adjustment is ever applied — a "month" in this API is
always exactly 2592000 seconds, that is thirty 86400-second days. Notice periods themselves are
whole numbers of days. Warranty and remediation instants are whole seconds, and the remediation
cooldown is exactly 259200 seconds, which is 72 hours.

**Two quantities are not rounded at all.** The project's derived posture is an enumerated value, so no
numeric rounding applies to it. And the three reconciliation deltas of section 2.9 are exact integer
identities: they are computed by integer subtraction and are never rounded, scaled or given any
tolerance, because their contract is that they equal zero and nothing else.

### 2.9. Conserved Quantities: Escrow Cash, Undivided Interest and Relocation Obligation

Three quantities in a conversion project are **conserved**, meaning the registry maintains a
book-balancing identity over them that must hold at the end of every single request. These are not
periodic reconciliations run by a batch job; they are recomputed inline, and a request that would
leave one of them out of balance is not a valid outcome of this API. Each identity is exposed on the
`ConversionProject` record as a delta field so that it can be inspected directly.

**Escrow cash is conserved between buckets.** Every earnest-money deposit that has ever reached
funded status is accumulated into `escrow_deposits_received_cents`, which only ever grows. That total
is then distributed across three mutually exclusive buckets according to each purchase agreement's
current escrow standing: `escrow_balance_cents` holds the deposits still on deposit,
`escrow_refunded_cents` holds those returned to purchasers, and `escrow_disbursed_cents` holds those
paid out at closing. The reconciliation field `escrow_reconciliation_delta_cents` is the received
total minus the sum of those three buckets, and **it must equal zero after every request**. Agreements
whose escrow standing is still `PENDING` contribute to none of the three buckets and are excluded from
the received total until they become funded, so a pending agreement is invisible to this identity
rather than a source of drift. The identity holds across compensating pairs as well: funding a deposit
and then rescinding the same agreement moves money from one bucket to another and leaves the delta at
zero.

**The undivided interest in the common elements is conserved by redistribution.** Unlike cash, which
moves between buckets, the ownership share is a fixed dimensionless allocation that is redivided among
units. Each unit's share is held in `percentage_interest_bp`, and the project's
`bp_conservation_total` is the sum of that field over the units whose declaration standing is
`INCLUDED`. Whenever `included_unit_count` is at least 1, `bp_conservation_total` must equal exactly
10000 basis points — the entire building, no more and no less. Withdrawing a unit pins that unit to 0
basis points and reallocates the full 10000 across the units that remain; reinstating it must restore
not only the conserved total but **every individual unit's `percentage_interest_bp` to its exact
pre-withdrawal value**, so that a withdraw-then-reinstate pair is observationally invisible.

**The relocation obligation owed to tenants is conserved between accrual and settlement.** Serving a
conversion notice on a tenant household accrues a relocation entitlement, and every entitlement ever
accrued is accumulated into the project's `relocation_obligation_accrued_cents`, which only ever
grows. Against that total the registry tracks three ledger fields: `relocation_paid_cents`, the sum of
each household's `relocation_paid_cents` where the obligation was actually disbursed;
`relocation_reversed_cents`, the sum of each household's `relocation_reversed_cents` where the
obligation was cancelled rather than paid — most typically because the household exercised its right
of first refusal and bought its own unit instead of relocating; and `relocation_outstanding_cents`, the
sum of `relocation_assistance_cents` over the households whose relocation standing is still `ACCRUED`
and therefore still owed. The field `relocation_reconciliation_delta_cents` is the accrued total minus
the sum of paid, reversed and outstanding, and **it too must equal zero after every request**,
including across the compensating pair of disbursing a household's assistance and then recording a
right-of-first-refusal exercise on it.

These three invariants are load-bearing rather than decorative. A non-zero value in either
`escrow_reconciliation_delta_cents` or `relocation_reconciliation_delta_cents` is itself one of the
conditions that holds a project out of the fully open posture, so a project that has drifted cannot
release a closing batch until the books balance again. Section 3 states, transition by transition,
which fields each accrual, payment and reversal writes.

## 3. Business Logic & Workflows

A condominium conversion is not a single transaction; it is a regulated sequence in which an existing rental building is inspected, re-platted into individually owned units, disclosed to prospective purchasers under a statutory offering document, cleared with its sitting tenants, and finally sold off in controlled batches. Each stage produces artefacts that later stages depend on, and almost every stage can be pushed backwards by a discovery made later — a rejected engineering report, a withdrawn unit, a material amendment to the offering statement, a purchaser exercising a rescission right. The subsections below walk that sequence and, at each step, state exactly which role may act, which states the acting entity must be in, what the system computes, and what it writes on neighbouring records.

Two conventions run through all of it. First, **every temporal decision in this system is made against a server-side logical clock**, never against wall-clock time. Second, **each entity's state lives in one or more named state fields**, and several entities carry more than one such field evolving independently on the same row; the prose always names the field alongside the state value, because a value like `SIGNED` belongs to `contract_status` while `FUNDED` belongs to `escrow_status`, and confusing the two dimensions produces a different system.

### 3.1. Project Intake, the Building Posture Gate, and the Logical Clock

A `ConverterSponsor` opens the file by registering a **conversion project**, supplying the `building_address` of the building being converted (a non-empty string of at most 200 characters), the `year_built` of original construction (a whole year no earlier than 1800 and no later than 2026, both endpoints accepted), the `total_unit_count` that the plat is expected to define (a whole number of at least 2 and at most 400, both endpoints accepted), and the `sponsor_user_id` that identifies the sponsoring operator. One further intake field is optional: `max_overlapping_remediations`, a project-wide ceiling on how many warranty remediation windows may cover any single instant across all building components. When it is omitted the project takes the value 2; when supplied it must be at least 1 and at most 5, both endpoints accepted.

Creation lands the project in `status` `FEASIBILITY` and `posture` `RESTRICTED`, with `suitability_gate` `UNEVALUATED`, `suitability_score` `0.00`, `included_unit_count` 0, every cents-denominated aggregate at 0, and `version` 1. The `status` field is the project's workflow phase and holds exactly one of `FEASIBILITY`, `SUITABILITY_REVIEW`, `DOCUMENTS_PREPARATION`, `REGISTRATION`, `PRESALE`, `CLOSINGS` or `COMPLETED`, with `COMPLETED` terminal. The `posture` field is an entirely independent gating dimension holding one of `OPEN`, `RESTRICTED` or `FROZEN`, and it is never set by hand — it is always re-derived from the project's children, as §3.1 describes below. `suitability_gate` holds `UNEVALUATED`, `PASSED` or `FAILED`.

Projects are listable with optional filters on `status`, `posture`, `suitability_gate` and `sponsor_user_id`, and the sponsor or a `PlatformAdmin` may later adjust three of the intake facts: `building_address`, `total_unit_count` and `max_overlapping_remediations`. Lowering `max_overlapping_remediations` is deliberately not retroactive — remediation windows already scheduled remain scheduled; the lowered ceiling only constrains scheduling requests that arrive afterwards. Every such adjustment increments the project's `version` by 1 and refreshes `updated_at`.

**Deriving the posture.** The posture is a first-match, top-down evaluation over the project's children and its own reconciliation fields, and the first branch that matches wins outright — a project that satisfies both a freezing clause and a restricting clause is `FROZEN`, and `RESTRICTED` is never reported for such a project.

The project is `FROZEN` if either of these holds: the project's `suitability_gate` is `FAILED`; or some `EngineeringReport` of the project sits in `status` `REVISION_REQUESTED`.

Otherwise the project is `RESTRICTED` if any one of eight clauses holds: the `suitability_gate` is `UNEVALUATED`; the project has no `DeclarationPackage` in `status` `RECORDED`; the project has no `PublicOfferingStatement` in `status` `EFFECTIVE`; some `ClosingBatch` of the project sits in `status` `THRESHOLD_SHORT`; some `TenantHousehold` of the project has `notice_status` `HOLDOVER`; some `TenantHousehold` of the project has `relocation_status` `ACCRUED` while its `rofr_status` is either `WAIVED` or `EXPIRED`; the project's `escrow_reconciliation_delta_cents` is any value other than 0; or the project's `relocation_reconciliation_delta_cents` is any value other than 0.

If neither the freezing nor the restricting branch matches, the posture is `OPEN`.

Five posture transitions are declared, all of them performed by the system rather than by a named human role, and all of them fired either by an explicit posture-recalculation request from a `ConverterSponsor`, a `StateRegulator` or a `PlatformAdmin`, or as a side effect of any other transition whose effects say the posture is recomputed. `RESTRICTED → OPEN` fires when the derivation evaluates to `OPEN`. `OPEN → RESTRICTED` fires when it evaluates to `RESTRICTED`. Both `RESTRICTED → FROZEN` and `OPEN → FROZEN` fire when it evaluates to `FROZEN`, and in practice the freezing edge is reached either by a peer reviewer rejecting an engineering report or by an explicit recalculation. `FROZEN → RESTRICTED` fires when a previously frozen project's derivation evaluates to `RESTRICTED` — typically after a fresh suitability assessment restores a passing gate. There is deliberately **no** `FROZEN → OPEN` edge: a thawing project always lands in `RESTRICTED` first, because it cannot satisfy the `OPEN` branch until its offering statement has been made `EFFECTIVE` again. Each of these five transitions writes the new `posture`, sets `last_posture_recalculated_at` to the current logical-clock instant, and increments the project's `version` by 1.

**What the posture gates.** A `FROZEN` posture rejects every write request against the project's graph with `ERR_PROJECT_FROZEN` (HTTP 409), with a pinned exemption list: setting the logical clock, creating a new conversion project, running a posture recalculation, creating an engineering report, adding a major component, adjusting a major component's engineering inputs, submitting a report, recording a peer-review decision, creating a suitability assessment, filing a warranty claim, and every warranty-claim transition (triage, remediation scheduling, completion, reopening) all remain permitted, as do all read operations. That exemption list is what makes a frozen project recoverable: the engineering and warranty tracks stay open precisely so the defect that froze the project can be corrected. A `RESTRICTED` posture rejects exactly one operation — releasing a closing batch — with `ERR_PROJECT_RESTRICTED` (HTTP 409); every other write is permitted. An `OPEN` posture rejects nothing on posture grounds.

**The posture recalculation sweep.** Requesting a posture recalculation does more than re-derive the posture: it runs four steps in this pinned order. Step one advances every `TenantHousehold` of the project whose `notice_status` is `NOTICE_SERVED` and whose `vacate_deadline_at` has been reached — that is, where the logical clock is at or after `vacate_deadline_at` — to `notice_status` `VACATE_DUE`, taking households in ascending `created_at` order. Step two moves every household whose `rofr_status` is `OFFERED` and whose `rofr_expires_at` is strictly in the past — the clock strictly after `rofr_expires_at` — to `rofr_status` `EXPIRED`, again in ascending `created_at` order. Step three closes every `WarrantyClaim` of the project whose `status` is `REMEDIATED` and whose `warranty_expires_at` is strictly in the past, moving `REMEDIATED → CLOSED` in ascending `created_at` order. Step four performs the first-match posture evaluation described above and writes `posture` and `last_posture_recalculated_at`. The project's `version` increments by 1 for the recalculation itself, and each swept child increments its own `version` by 1.

**The logical clock.** Every deadline, notice period, rescission window, right-of-first-refusal window, warranty expiry, remediation cooldown, closing-batch settlement window and useful-life horizon in this system is evaluated against a single server-side logical clock and nothing else. On startup that clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time. An administrative test-driving capability moves it: the caller supplies a `current_utc` instant and the clock is set to it. Moving the clock does not by itself fire any state transition — nothing expires merely because time passed. Expiries are realised only when a posture recalculation sweep runs, or when a request that itself carries a temporal precondition is evaluated. A companion read returns the clock's current instant, which is what test harnesses and operators use to reason about where each deadline sits.

**Request evaluation order.** Because many rules can fail on a single request, the order in which they are evaluated is itself part of the contract, and a request that violates several rules always reports the earliest one in the following ordering. Authentication comes first: a request missing either the `X-User-ID` or the `X-User-Role` header, presenting either as empty, or presenting a role name that is not one of the nine declared roles — `ConverterSponsor`, `LicensedEngineer`, `PeerReviewEngineer`, `StateRegulator`, `EscrowAgent`, `LenderUnderwriter`, `PlatformAdmin`, `TenantOccupant`, `Purchaser` — is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401). Second, a well-formed identity acting on an operation its role is not authorised for is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403). Third, the two entity-backed roles must be acting on their own record: a `TenantOccupant` answering a right-of-first-refusal offer must present an `X-User-ID` equal to the addressed `TenantHousehold`'s `id`, and a `Purchaser` exercising rescission must present an `X-User-ID` equal to the addressed `PurchaseAgreement`'s `id`; otherwise the request fails with `ERR_IDENTITY_MISMATCH` (HTTP 403). Fourth, segregation of duties on peer review: a review decision whose acting `X-User-ID` equals the report's `submitted_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Existence checks follow, in a fixed order of their own. An unresolvable conversion-project identifier anywhere in the addressed hierarchy yields `ERR_PROJECT_NOT_FOUND` (HTTP 404). Next, an unresolvable engineering report, major component or suitability assessment — whether it was addressed directly or supplied in a request body as `engineering_report_id` or `major_component_id` — yields `ERR_ENGINEERING_ARTIFACT_NOT_FOUND` (HTTP 404); this check also guards reserve-study creation and warranty-claim filing. Then an unresolvable declaration package or unit, addressed directly or supplied as `declaration_package_id`, `occupied_unit_id`, `unit_id` or `reported_by_unit_id`, yields `ERR_DECLARATION_ARTIFACT_NOT_FOUND` (HTTP 404); it guards every declaration-package and unit operation as well as tenant-household registration, offering-statement creation and warranty-claim filing. Then an unresolvable offering statement, or a statutory section code that is not one of the nine declared members, yields `ERR_DISCLOSURE_ARTIFACT_NOT_FOUND` (HTTP 404). Then an unresolvable tenant household — addressed directly, or supplied as a non-null `tenant_household_id` when signing a purchase agreement — yields `ERR_TENANT_NOT_FOUND` (HTTP 404). Then an unresolvable reserve study or initial budget, addressed directly or supplied as `reserve_study_id` or `initial_budget_id`, yields `ERR_FINANCIAL_ARTIFACT_NOT_FOUND` (HTTP 404); it guards budget adoption, budget creation and offering-statement creation. Then an unresolvable purchase agreement or closing batch, addressed directly or supplied as `purchase_agreement_id`, yields `ERR_SALES_ARTIFACT_NOT_FOUND` (HTTP 404). Finally an unresolvable warranty claim yields `ERR_CLAIM_NOT_FOUND` (HTTP 404).

Once everything referenced exists, the system checks that everything referenced belongs to the same conversion project. The `conversion_project_id` of the referenced engineering report, unit, tenant household, purchase agreement, reserve study, initial budget and closing batch, and the `conversion_project_id` of the report owning a referenced major component, must all be equal to the project in scope; a mismatch is `ERR_PROJECT_SCOPE_MISMATCH` (HTTP 409). This scope check guards reserve-study creation, budget creation, offering-statement creation, tenant-household registration, warranty-claim filing, assignment of an agreement to a closing batch, and purchase-agreement signature.

Request shape is checked next: every required body field present, every type correct, every enum value a declared member of its set, every integer inside its declared range, and every datetime a valid ISO 8601 UTC instant — otherwise `ERR_INVALID_REQUEST` (HTTP 422). Listing operations additionally validate paging: `limit` must be a whole number from 1 through 100 inclusive and `offset` a whole number of at least 0, or the request fails with `ERR_INVALID_PAGINATION` (HTTP 422). Then uniqueness: the pairs (`conversion_project_id`, `report_label`), (`engineering_report_id`, `component_type`), (`declaration_package_id`, `unit_number`), (`public_offering_statement_id`, `section_code`), (`conversion_project_id`, `fiscal_year_label`), (`conversion_project_id`, `batch_sequence_no`) and (`conversion_project_id`, `household_label`) must each be unique, and a project may carry at most one `DeclarationPackage` and at most one `PublicOfferingStatement`; a violation is `ERR_DUPLICATE_KEY` (HTTP 409).

Only after all of that do the four stale-parent-version checks run, then the posture gates (`ERR_PROJECT_FROZEN` before `ERR_PROJECT_RESTRICTED`), then the state-machine check itself: if the target entity's current value in the relevant state field is not a declared source state for the requested transition — including a terminal state that can no longer move and a repeated trigger that has already been applied — the request is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Everything else — the batch-release, disclosure, temporal, safety, referential, constraint and fiscal rules described throughout the remaining subsections — is evaluated after that, in the order in which those subsections introduce them.

### 3.2. Engineering Reports, Component Inventories and Independent Peer Review

Suitability of a rental building for conversion is established by an **engineering report** on the remaining useful life of the building's major components. Either a `LicensedEngineer` or the `ConverterSponsor` opens one against a project, supplying a `report_label` that must be non-empty and unique among that project's reports, the `inspection_date` on which the physical inspection was performed, and the `submitted_by_user_id` of the engineer of record. A new report carries `status` `DRAFT`, `revision_round` 0, `verified_component_count` 0, `total_replacement_cost_cents` 0 and `version` 1. Reports of a project are listable and filterable by `status`; the report's own `conversion_project_id` is what ties it to the building. The `status` field holds one of `DRAFT`, `SUBMITTED`, `ACCEPTED`, `REVISION_REQUESTED` or `SUPERSEDED`, and `SUPERSEDED` is terminal.

Inside a `DRAFT` report the `LicensedEngineer` inventories the building system by system. Each **major component** row carries the `engineering_report_id` of its report and a `component_type` drawn from `ROOF`, `ELEVATOR`, `HVAC`, `PLUMBING_RISERS`, `ELECTRICAL_SERVICE`, `FACADE`, `FOUNDATION`, `PARKING_DECK` and `FIRE_SUPPRESSION`, unique within its report. The engineer states `remaining_useful_life_years` as a whole number from 0 through 80 inclusive and `effective_age_years` — the useful life already consumed, which is what drives the fully funded reserve balance — as a whole number from 0 through 120 inclusive. Money enters as `replacement_cost_cents`, the current cost to replace that component, which must be at least 0. The portion of that cost already funded is recorded as `funded_pct_bp` in basis points, a whole number from 0 through 10000 inclusive (10000 basis points meaning the component is fully funded), defaulting to 0 when omitted. The inspected condition class arrives as `condition_rating`, one of `EXCELLENT`, `GOOD`, `FAIR` or `POOR`, and it drives the condition penalty in the suitability score.

Three further component facts are optional and each defaults to a "no special treatment" value. `planned_remediation_gain_years` — a whole number from 0 through 40 inclusive, defaulting to 0 — records how many years of useful life the sponsor's planned remediation would add, and it is consulted only by the post-remediation variant of the suitability score. `is_life_safety`, defaulting to false, marks components subject to the critical life-safety cap. `is_structural`, defaulting to false, selects the longer of the two common-element warranty windows. Every new component row starts with `verification_status` `UNVERIFIED`, and components are listable within their report with filters on `verification_status`, `component_type`, `is_life_safety` and `is_structural`. Adding a component recomputes the parent report's `total_replacement_cost_cents` and starts the component at `version` 1.

Only the `PeerReviewEngineer` can flip a component into the verified population. That role submits a `verified` boolean: true sets `verification_status` to `VERIFIED`, false sets it back to `UNVERIFIED`. Either way the parent report's `verified_component_count` is recomputed and the component's `version` increments by 1. This is the single lever that decides which components feed the suitability score and the reserve study; declining to verify anything at all is what produces the empty-population fallbacks those two calculations define.

A `LicensedEngineer` may also revise a component's engineering inputs after the fact, adjusting any of `remaining_useful_life_years`, `effective_age_years`, `replacement_cost_cents`, `funded_pct_bp`, `condition_rating`, `planned_remediation_gain_years`, `is_life_safety` and `is_structural`. Such an adjustment always recomputes the report's `total_replacement_cost_cents` and `verified_component_count` and increments the component's `version` by 1, and it carries two consequences depending on where the parent report sits. If the parent report was in `status` `ACCEPTED`, the edit invalidates the accepted engineering opinion: the report moves `ACCEPTED → SUPERSEDED`, the project's `suitability_gate` is reset to `UNEVALUATED`, and the project's posture is recomputed. If instead the parent report was in `status` `REVISION_REQUESTED`, the edit reopens the drafting cycle and the report moves `REVISION_REQUESTED → DRAFT`.

**Submission.** When the inventory is complete the `LicensedEngineer` submits the report, moving its `status` `DRAFT → SUBMITTED`. Two preconditions apply: the report must currently be in `DRAFT`, and it must have at least one child major component — a report with an empty inventory cannot be submitted. Submission records the acting `X-User-ID` as the report's `submitted_by_user_id`, increments `revision_round` by 1 (so `revision_round` always counts completed `DRAFT → SUBMITTED` submissions, and a report resubmitted after a revision round reaches 2), sets `verification_status` to `VERIFIED` on every child major component, recomputes `verified_component_count` and `total_replacement_cost_cents` over those children, and increments the report's `version` by 1.

Submission also bubbles up. When the acting project is still in `status` `FEASIBILITY` and the submitted report's `conversion_project_id` is that project, the system moves the project `FEASIBILITY → SUITABILITY_REVIEW`, recomputes the project's `posture`, and increments the project's `version` by 1. Later submissions on the same project do not repeat that move, because the project is no longer in `FEASIBILITY`.

**Peer review is a fork with two disjoint outcomes.** A `PeerReviewEngineer` records a decision carrying `decision` (either `ACCEPT` or `REJECT`), the `reviewed_by_user_id` of the reviewer, and an optional `review_note`. Both branches require the report to be in `status` `SUBMITTED` and both enforce segregation of duties — the acting `X-User-ID` must differ from the report's `submitted_by_user_id`, or the decision is refused with `ERR_SEGREGATION_OF_DUTIES`. From there the branches diverge completely.

On `ACCEPT` the report moves `SUBMITTED → ACCEPTED`. This branch carries one extra precondition: the report's `verified_component_count` must be at least 1, so a report whose components were never verified cannot be accepted. Acceptance records the acting `X-User-ID` as the report's `reviewed_by_user_id`; then, because a project may rest on only one accepted engineering opinion at a time, **every other** engineering report of the same `conversion_project_id` that currently sits in `status` `ACCEPTED` is moved `ACCEPTED → SUPERSEDED`, processed in ascending `created_at` order. That supersession is itself a declared transition with its own consequence: each superseded report has every one of its `SuitabilityAssessment` rows whose `status` is `EFFECTIVE` moved to `INVALIDATED`, and each superseded report increments its own `version` by 1. The accepting report increments its `version` by 1. Acceptance accrues no project freeze and touches neither the project's `suitability_gate` nor its `status` — a fresh assessment must still be run before the project can move on.

On `REJECT` the report moves `SUBMITTED → REVISION_REQUESTED`, and the effect set is entirely disjoint from the accept branch: nothing is superseded, and instead a four-hop punitive cascade runs, each hop caused by the one before it.

Hop one writes the report itself: `status` becomes `REVISION_REQUESTED`, `reviewed_by_user_id` becomes the acting `X-User-ID`, and `verification_status` is set to `UNVERIFIED` on **every** child major component, which drives `verified_component_count` to 0 and `total_replacement_cost_cents` to 0 on the report.

Hop two follows from hop one: because no child component is `VERIFIED` any longer, every `SuitabilityAssessment` of this report whose `status` is `EFFECTIVE` moves to `INVALIDATED`.

Hop three follows from hop two: because the project now has no `EFFECTIVE` suitability assessment left, the project's `suitability_gate` is set to `FAILED`, its `suitability_score` is reset to `0.00`, and its `status` moves `DOCUMENTS_PREPARATION → SUITABILITY_REVIEW`. That project transition has its own preconditions — the project must be in `DOCUMENTS_PREPARATION`, and every suitability assessment of the rejected report must already carry `status` `INVALIDATED`, which hop two guarantees — and it recomputes the project's posture and increments the project's `version` by 1.

Hop four follows from hop three: because `suitability_gate` is now `FAILED`, the posture derivation's first branch matches and the project's `posture` becomes `FROZEN`; and the project's `PublicOfferingStatement`, if it currently sits in `status` `EFFECTIVE`, is moved `EFFECTIVE → AMENDMENT_REQUIRED`, incrementing that statement's `version` by 1. The rejected report increments its own `version` by 1.

**Closing the revision cycle.** A report in `REVISION_REQUESTED` is not dead. The `LicensedEngineer` reopens it, moving `REVISION_REQUESTED → DRAFT` and incrementing the report's `version` by 1, either by explicitly requesting a revision — optionally attaching a `revision_note` to explain what will change — or, equivalently, by adjusting any child component whose `engineering_report_id` is that report. Either route requires the report to be in `REVISION_REQUESTED`. Once back in `DRAFT` the engineer corrects the inventory and submits again, and `revision_round` increments once more. The full cycle is therefore `DRAFT → SUBMITTED → REVISION_REQUESTED → DRAFT → SUBMITTED`, and it may repeat without bound; `revision_round` is the running count of how many times the report has been put forward.

### 3.3. Scoring Building Suitability and Setting the Suitability Gate

An accepted engineering report is evidence; a **suitability assessment** is the decision drawn from it. Either a `PeerReviewEngineer` or the `ConverterSponsor` creates an assessment against a report, choosing a `variant` — `AS_INSPECTED` or `POST_REMEDIATION` — and supplying `expected_engineering_report_version`, which must carry the client's last observed `version` of that `EngineeringReport`. If the report's current `version` differs from the supplied value, the request is rejected with `ERR_STALE_REPORT_VERSION` (HTTP 412). This guard is not a state precondition — creating a further assessment on the same report is perfectly legitimate from an unchanged report state — but a new assessment supersedes the prior effective one and rewrites the project's `suitability_gate` and `suitability_score` off the superseded row, so a client working from a report version that has since advanced would be overwriting a verdict it never saw.

The assessment row records the `engineering_report_id` it was computed from and copies the report's `conversion_project_id` onto itself at creation, alongside the requested `variant`, the computed `score`, the `basis` on which it was computed, a `critical_cap_applied` flag and a `verdict`. Its own `status` starts at `EFFECTIVE` and holds one of `EFFECTIVE`, `SUPERSEDED` or `INVALIDATED`. Assessments are listable within a report and across the estate, filterable by `variant`, `verdict` and `status`, and the cross-cutting list additionally accepts `conversion_project_id` and `engineering_report_id` filters so the two variants of the same report can be read side by side.

**The scored population is pinned.** Only the report's own child major components whose `verification_status` is `VERIFIED` participate. `UNVERIFIED` components are excluded entirely — they add neither weight nor denominator — and components belonging to sibling reports or to `SUPERSEDED` reports are never included under any circumstances.

**The empty-population fallback.** When the verified population is empty the calculation does not fail; it records `basis` `NO_VERIFIED_COMPONENTS`, `score` `0.00`, `critical_cap_applied` false, and `verdict` `FAILED` — the last of these because `0.00` falls short of the passing score. Whenever there is at least one verified component the `basis` is `VERIFIED_COMPONENTS` and the weighted computation below runs.

**The weighted computation.** First the system sums `replacement_cost_cents` across the verified population to obtain a cost total. Each component then receives a cost weight: normally its own `replacement_cost_cents` divided by that cost total, but when the cost total is exactly 0 — every verified component having a zero replacement cost — every component instead carries an equal weight of one divided by the number of verified components. These weights are held as exact fractions and are not rounded at this stage.

Each component then contributes a remaining-life factor. The raw remaining life in years is divided by a thirty-year useful-life horizon, and the result is clamped into the range from 0 through 1 inclusive: a component with 45 remaining years scores the same 1 as one with exactly 30, and a component with 0 remaining years scores 0. From that factor the system subtracts the component's condition penalty, read from its `condition_rating`: `EXCELLENT` carries no penalty at all, `GOOD` carries a penalty of 0.05, `FAIR` carries 0.15, and `POOR` carries 0.35. The difference is then floored at 0, so a badly rated component with little life left contributes nothing rather than a negative amount. The component's contribution is its cost weight multiplied by that floored difference, and the raw building score is the exact sum of all component contributions, accumulated without intermediate rounding.

**The life-safety critical cap.** After the sum is complete and before any rounding, the system tests whether the critical cap applies: it applies when any component in the verified population has `is_life_safety` true and a remaining life of strictly fewer than 5 years. Strictly fewer matters — a life-safety component with exactly 5 remaining years does not trigger the cap. When the cap applies, `critical_cap_applied` is recorded as true and the raw score is clamped down to at most 0.40; a raw score already below 0.40 is left untouched. When it does not apply, `critical_cap_applied` is false.

**Rounding is applied exactly once.** The (possibly capped) raw score is multiplied by 100 and that single product is rounded half-up to two decimal places to produce `score`, which therefore always lies between `0.00` and `100.00` inclusive. Contributions are never rounded individually and the score is never rounded twice. The `verdict` is then `PASSED` when `score` is greater than or equal to the passing score of `62.50` — a score of exactly `62.50` passes — and `FAILED` otherwise.

**The two variants diverge in three places.** Under `AS_INSPECTED` the remaining-life factor uses the component's `remaining_useful_life_years` as inspected, and the condition penalty is exactly the penalty for its `condition_rating` — 0.00, 0.05, 0.15 or 0.35 as listed above. Under `POST_REMEDIATION` the remaining life used is `remaining_useful_life_years` plus `planned_remediation_gain_years`, the condition penalty is the smaller of the component's own condition penalty and a post-remediation penalty floor of 0.05 (so `EXCELLENT` still carries 0.00 and `GOOD` still carries 0.05, while `FAIR` and `POOR` are both reduced to 0.05), and — importantly — the critical-cap test also uses the extended remaining life, so a life-safety component remediated up to 5 or more years no longer triggers the cap at all. The practical consequence is that for an identical set of component rows, `POST_REMEDIATION` yields a strictly higher score than `AS_INSPECTED` whenever any component has a `planned_remediation_gain_years` above 0 or a `condition_rating` of `FAIR` or `POOR`; for a building of pristine components with no planned remediation the two variants agree.

**Projecting the verdict onto the project.** Creating an assessment supersedes the prior work on the same footing: any earlier `SuitabilityAssessment` row of the same report and the same `variant` whose `status` is `EFFECTIVE` moves to `SUPERSEDED`. The project's `suitability_score` is then set to the new assessment's `score` and its `suitability_gate` is set to `PASSED` when the `verdict` is `PASSED` and to `FAILED` otherwise. In general the project's `suitability_gate` and `suitability_score` always mirror the latest assessment that is not `SUPERSEDED`, and where the project has no such assessment at all the score reads `0.00`. Finally the project's posture is recomputed and the parent report's `version` increments by 1.

A passing verdict additionally advances the workflow. When the project is in `status` `SUITABILITY_REVIEW` and the assessment just created carries `verdict` `PASSED`, the system moves the project `SUITABILITY_REVIEW → DOCUMENTS_PREPARATION`, writing `suitability_gate` `PASSED` and `suitability_score` equal to the assessment's `score`, recomputing the posture, and incrementing the project's `version` by 1. This is also the route by which a frozen project thaws: with the gate back to `PASSED` and no report left in `REVISION_REQUESTED`, the freezing branch of the posture derivation no longer matches and the project moves `FROZEN → RESTRICTED`.

The gate is consumed downstream. Certifying a plat and creating a reserve study both require the project's `suitability_gate` to read `PASSED`; either request against a project whose gate is `UNEVALUATED` or `FAILED` is rejected with `ERR_SUITABILITY_GATE_FAILED` (HTTP 409).

### 3.4. The Declaration, Bylaws and Plat: Unit Boundaries and the Undivided-Interest Sweep

Creating the condominium regime means recording an instrument. The `ConverterSponsor` opens a **declaration package** against the project — at most one per `conversion_project_id` — supplying `declaration_text_ref` and `bylaws_text_ref` as non-empty storage references for the declaration instrument and the bylaws, and a `boundary_convention` that governs how every unit's boundary is drawn: `PAINT_TO_PAINT`, `STUD_TO_STUD` or `CENTERLINE`. A new package carries `status` `DRAFT`, `plat_revision` 0, `allocated_bp_total` 0, a null `recorded_at`, and `version` 1. Its `status` holds one of `DRAFT`, `PLAT_CERTIFIED` or `RECORDED`, with `RECORDED` terminal. While the package is in `DRAFT` the sponsor may adjust `declaration_text_ref`, `bylaws_text_ref` and `boundary_convention`; packages are listable per project with a `status` filter.

Within the package the sponsor — or a `LicensedEngineer` — defines the individual **units**. Each unit carries the `declaration_package_id` of the plat that defines its boundaries and copies the package's `conversion_project_id` onto itself at creation. It is designated by a `unit_number`, a non-empty string unique within its package, sits on a `floor_level` given as a whole number from -3 through 80 inclusive (negative values denoting below-grade floors), and encloses `heated_square_feet` of heated area inside the declared boundary, which must be at least 100. A non-empty `boundary_note` of at most 500 characters states in words how that unit's boundary runs under the package's convention. The economic heart of the unit is `base_percentage_interest_bp`: its as-declared undivided interest in the common elements, expressed in basis points as a whole number from 1 through 10000 inclusive. That figure is the immutable declared basis, and for the plat to certify, the sum of `base_percentage_interest_bp` over all sibling units must itself total 10000.

A newly defined unit starts with `declaration_status` `INCLUDED` and `sale_status` `UNSOLD`, and its effective `percentage_interest_bp` is seeded from `base_percentage_interest_bp` until the next reallocation sweep overwrites it. Its `unit_annual_assessment_cents` and `unit_monthly_assessment_cents` both start at 0, and the unit starts at `version` 1. The project's `included_unit_count` — which is simply the number of the project's units whose `declaration_status` is `INCLUDED` — is recomputed. Defining a unit inside a package that had already been certified is a structural change to the plat, so the package falls back `PLAT_CERTIFIED → DRAFT`. `declaration_status` holds `INCLUDED` or `WITHDRAWN`; `sale_status` holds `UNSOLD`, `UNDER_CONTRACT`, `HARD_CONTRACT` or `SOLD` and is always derived from the unit's purchase agreements rather than set by hand.

Units are listable within their package and across the estate, filterable by `declaration_status` and `sale_status`, and the estate-wide list also accepts `conversion_project_id` and `declaration_package_id` filters. While a unit is still `UNSOLD` the sponsor or a `LicensedEngineer` may adjust its `boundary_note`, `heated_square_feet`, `floor_level` and `base_percentage_interest_bp`, incrementing the unit's `version` by 1. Because `base_percentage_interest_bp` is the declared economic basis, changing it on a certified plat also forces the package `PLAT_CERTIFIED → DRAFT` so that the allocation must be derived again from scratch.

**The undivided-interest reallocation sweep.** The effective `percentage_interest_bp` of each unit is never entered by hand; it is a pure function of the current `INCLUDED` set of the package, which is exactly what makes withdrawal and reinstatement compensating operations. The sweep runs whenever a plat is certified and whenever a unit is withdrawn or reinstated, and it proceeds as follows over the package's units taken in ascending `created_at` order.

Every unit whose `declaration_status` is `WITHDRAWN` is pinned to a `percentage_interest_bp` of 0 and excluded from the rest of the computation. If no unit of the package is `INCLUDED` — a state reachable only before certification — both the package's `allocated_bp_total` and the project's `bp_conservation_total` are set to 0 and the sweep ends. Otherwise the system sums `base_percentage_interest_bp` over the `INCLUDED` units to obtain a base sum. Each included unit's exact raw share is then 10000 multiplied by its own `base_percentage_interest_bp` and divided by that base sum. Each raw share is **truncated** to a whole basis point — the fractional part is discarded, never rounded — and the residual is what remains of 10000 after those truncated values are summed; because truncation loses strictly less than one basis point per unit, the residual is always at least 0 and strictly fewer than the number of included units.

The residual is then distributed one basis point at a time. The included units are sorted by the fractional part of their raw share in descending order; ties on that fractional part are broken by `base_percentage_interest_bp` in descending order, and any remaining tie is broken by `created_at` in ascending order. Walking that sorted list from the front, each unit in turn receives one additional basis point until the residual is exhausted. The list is never wrapped around, because the residual can never reach the number of included units. Each included unit's `percentage_interest_bp` is then written, the package's `allocated_bp_total` is set to the sum of those values, and the project's `bp_conservation_total` is set to the same figure. The **conserved invariant** is absolute: whenever the package has at least one `INCLUDED` unit, the `INCLUDED` set's `percentage_interest_bp` values total exactly 10000 basis points, no more and no less.

Because the sweep reads only the current `INCLUDED` set and the immutable declared bases, it is exactly compensating. Consider three units declared at 3333, 3333 and 3334 basis points: with all three included, the raw shares are exactly 3333, 3333 and 3334, the residual is 0, and the effective interests equal the declared ones. Withdraw the 3334-point unit and the base sum becomes 6666, the two survivors' raw shares are exactly 5000 each, the residual is again 0, and the effective interests become 5000 and 5000 with the withdrawn unit pinned to 0. Reinstate that unit and the base sum returns to 10000, restoring 3333, 3333 and 3334 exactly — both the conserved total of 10000 and every individual unit's value are restored, not merely approximated.

**Certifying the plat.** The sponsor certifies the plat to move the package `DRAFT → PLAT_CERTIFIED`. Six preconditions apply. The package must currently be in `DRAFT`; the package must have at least one child unit whose `declaration_status` is `INCLUDED`; the reallocation must balance, meaning `allocated_bp_total` recomputed over the `INCLUDED` set equals exactly 10000 basis points, and a mismatch is refused with `ERR_PERCENTAGE_INTEREST_NOT_BALANCED` (409); the project's `suitability_gate` must read `PASSED`, otherwise `ERR_SUITABILITY_GATE_FAILED` (409); no `MajorComponent` of the project's `ACCEPTED` engineering report may be at once `verification_status` `VERIFIED`, `is_life_safety` true and carrying `remaining_useful_life_years` strictly fewer than 5, and a component that breaches this is refused with `ERR_LIFE_SAFETY_COMPONENT_EXPIRED` (422) — the comparison is strict, so a life-safety component with exactly 5 remaining years certifies without complaint while one with 4 does not; and the project's `posture` must not be `FROZEN`. Certification sets `status` to `PLAT_CERTIFIED`, runs the reallocation sweep over the `INCLUDED` unit set, and increments the package `version` by 1.

**Reverting a certified plat.** The `PLAT_CERTIFIED → DRAFT` edge is a system-driven fallback, never a sponsor request in its own right. It fires whenever the composition or the economics of the certified unit set change beneath it: withdrawing a unit of the package, reinstating a withdrawn unit of the package, defining a new unit inside the package, or changing an existing unit's `base_percentage_interest_bp`. Its preconditions are that the package is in `PLAT_CERTIFIED` and that the affected unit's `declaration_package_id` matches the package. The revert sets `status` back to `DRAFT`, increments `plat_revision` by 1 — so `plat_revision` is a running count of how many times a certified plat has had to be reopened — and increments `version` by 1. Because the edge writes `plat_revision`, a package that has been certified, reverted and certified again is distinguishable from one certified on the first attempt even though both read `PLAT_CERTIFIED`.

**Recording the declaration.** The sponsor records the certified package to move it `PLAT_CERTIFIED → RECORDED`, which is the terminal state of the package dimension: nothing moves a recorded package again. The package must be in `PLAT_CERTIFIED`; `allocated_bp_total` must still equal exactly 10000 basis points, again guarded by `ERR_PERCENTAGE_INTEREST_NOT_BALANCED`; the life-safety screen is applied a second time here, again with `ERR_LIFE_SAFETY_COMPONENT_EXPIRED`; an `InitialBudget` of the project must have `status` `ADOPTED` and the reserve study that budget references must have `adoption_status` `ADOPTED`, otherwise `ERR_RESERVE_STUDY_NOT_ADOPTED` (409); every `TenantHousehold` of the project must have advanced past `PRE_NOTICE` on its `notice_status`, and a project with an un-noticed household is refused as an invalid transition; and `posture` must not be `FROZEN`. Recording writes `recorded_at` on the package from the logical clock, writes the project's `declaration_recorded_at` and `warranty_start_at` to that very same instant — so the statutory warranty clock for common elements begins at recording, not at any closing — moves the project `DOCUMENTS_PREPARATION → REGISTRATION`, and increments the package `version` by 1.

**The unit-withdrawal cascade.** Withdrawing a unit is the widest-reaching single act in the system, and its hops must be applied in order because each is caused by the one before it. The sponsor withdraws a unit with an optional `withdrawal_reason` recorded on the unit. Before anything else, the system checks that after the withdrawal at least one unit of the package would still be `INCLUDED`; withdrawing the last remaining included unit is refused with `ERR_LAST_INCLUDED_UNIT` (409), which keeps the reallocation denominator non-zero and keeps the conserved 10000 basis points meaningful.

Hop one sets the unit's `declaration_status` to `WITHDRAWN` and increments the unit's `version` by 1. Hop two, caused by that status write, voids the live sales on the unit: every `PurchaseAgreement` whose `unit_id` is this unit and whose `contract_status` is `SIGNED` moves `SIGNED → VOID`, and every such agreement whose `contract_status` is `HARD` moves `HARD → VOID`. Hop three, caused by each voiding in hop two, refunds the money: each voided agreement whose `escrow_status` is `FUNDED` moves `FUNDED → REFUNDED`, and for each one the project's `escrow_balance_cents` is decreased by that agreement's `deposit_cents` while `escrow_refunded_cents` is increased by the identical figure, keeping escrow cash conserved to the cent. Hop four, caused by hop three removing those agreements from the qualifying population, re-evaluates every `ClosingBatch` of the project that had one of the voided agreements assigned: a batch reading `THRESHOLD_MET` or `RELEASED` whose recomputed presale figures no longer clear the threshold falls back to `THRESHOLD_SHORT`, and a batch that leaves `RELEASED` also has `released_at` cleared to null and drags the project `CLOSINGS → PRESALE`. Hop five, caused by the composition change, reverts the package `PLAT_CERTIFIED → DRAFT` with `plat_revision` incremented. Hop six re-runs the reallocation sweep over the shrunken `INCLUDED` set, rewriting `percentage_interest_bp` on every unit of the package, pinning the withdrawn unit to 0, and rewriting `allocated_bp_total` and `bp_conservation_total` so they again total exactly 10000. Hop seven, caused by hop one, moves the project's `PublicOfferingStatement` `EFFECTIVE → AMENDMENT_REQUIRED`, because a disclosure document that describes a unit no longer being converted has become inaccurate. Finally `included_unit_count` is recomputed and `posture` is recalculated, which for a project that just lost a released batch resolves to `RESTRICTED`.

Reinstatement is the compensating act and is deliberately narrower. The sponsor reinstates a withdrawn unit, taking `declaration_status` from `WITHDRAWN` back to `INCLUDED`, reverting the package `PLAT_CERTIFIED → DRAFT`, re-running the sweep over the enlarged `INCLUDED` set, recomputing `included_unit_count` and `bp_conservation_total`, and incrementing the unit's `version` by 1. Voided purchase agreements are **not** revived and refunded escrow is **not** re-collected: the sales pipeline is not reversible, only the interest allocation is. A withdrawal followed by a reinstatement of the same unit therefore restores every unit's `percentage_interest_bp` and the conserved 10000-basis-point total exactly, while leaving the voided agreements void, the refunds refunded, and `plat_revision` two higher than it started.

### 3.5. Reserve Funding Studies and the First-Year Budget

A reserve study translates the verified component inventory into money. The sponsor or a `LicensedEngineer` commissions one against a project, supplying the `engineering_report_id` of the `ACCEPTED` report that furnishes the component data, the `method` to run — either `COMPONENT_METHOD` or `CASH_FLOW_METHOD` — and optionally `opening_reserve_balance_cents`, the cash the sponsor undertakes to seed the reserve account with at recording, which defaults to 0 and may never be negative. The study copies `conversion_project_id` from the parent. Two gates guard commissioning: the project's `suitability_gate` must read `PASSED`, refused otherwise with `ERR_SUITABILITY_GATE_FAILED` (409), and the referenced report must have at least one `MajorComponent` at `verification_status` `VERIFIED`, refused otherwise with `ERR_NO_VERIFIED_COMPONENTS` (409). A new study begins at `adoption_status` `PROPOSED` and `version` 1, and `adoption_status` thereafter holds `PROPOSED`, `ADOPTED` or `SUPERSEDED`.

The population is pinned and identical for both methods except where stated: the components of the study's referenced report whose `verification_status` is `VERIFIED`, always iterated in ascending `created_at` order. `UNVERIFIED` components and components belonging to any other report are excluded outright, which is why re-verifying a component and re-commissioning a study changes the money while the report's own text does not.

**The fully funded balance** is computed the same way under both methods and lands in `fully_funded_balance_cents`. For each component in turn, the denominator is that component's `effective_age_years` plus its `remaining_useful_life_years`; if that denominator is 0 the component contributes 0 cents outright, avoiding a division by zero for a component recorded with no age and no remaining life. Otherwise the component contributes its `replacement_cost_cents` multiplied by its `effective_age_years` and divided by that denominator, rounded half up to whole cents. The rounding order is pinned: **each component is rounded to whole cents first, and only then are the rounded amounts summed**. Summing the exact rational shares and rounding the total once is not the contract and yields a different figure.

**Under `COMPONENT_METHOD`** each component is funded independently on a straight line. A component's unfunded replacement cost is its `replacement_cost_cents` multiplied by the difference between 10000 and its `funded_pct_bp`, divided by 10000 — so a component recorded at `funded_pct_bp` of 2500 is treated as three quarters unfunded. That unfunded amount is spread over the greater of 1 and the component's `remaining_useful_life_years`, which keeps a component already at 0 remaining years from producing an infinite charge. Each component's annual amount is rounded **up** to whole cents — a ceiling, not a half-up round — and those per-component amounts are then summed into `recommended_annual_contribution_cents`. This method ignores `opening_reserve_balance_cents` entirely and ignores the horizon entirely, so a component with 45 remaining years still generates an annual charge.

**Under `CASH_FLOW_METHOD`** the reserve is treated as a single pooled account that must never breach a floor. The floor is 25000 cents per unit multiplied by the project's `total_unit_count`. The expenditure schedule replaces each component at the year given by the greater of 1 and its `remaining_useful_life_years`, at its full `replacement_cost_cents`; components whose maturity year exceeds the 30-year horizon are dropped from this method's population altogether, which is the one population difference between the methods. For each year from 1 through 30 ascending, the cumulative replacement spend through that year is the sum of `replacement_cost_cents` over the components maturing in that year or earlier; the requirement for that year is the floor plus that cumulative spend less `opening_reserve_balance_cents`, divided by the year number, rounded **up** to whole cents. The running requirement is the largest such year-requirement encountered, and `recommended_annual_contribution_cents` is that maximum or 0, whichever is greater — a project with an opening balance already exceeding every year's need contributes nothing. The two methods therefore diverge on the same component set whenever any two components' remaining useful lives differ or `opening_reserve_balance_cents` exceeds 0: `COMPONENT_METHOD` charges per component regardless of the pool, while `CASH_FLOW_METHOD` solves for the single smallest level contribution that keeps the pool at or above the floor at every year end.

Both methods share a tail. When `fully_funded_balance_cents` is 0, `percent_funded_bp` is 0. Otherwise `percent_funded_bp` is 10000 multiplied by `opening_reserve_balance_cents`, divided by `fully_funded_balance_cents`, rounded half up to a whole basis point. `funding_status` then reads `ADEQUATE` when `percent_funded_bp` is **at or above** 7000 basis points and `UNDERFUNDED` below it; the comparison is inclusive, so a study sitting at exactly 7000 basis points — seventy percent funded — is `ADEQUATE`, while 6999 is `UNDERFUNDED`. While a study is still `PROPOSED` the sponsor may adjust `opening_reserve_balance_cents`, which re-derives `percent_funded_bp` and `funding_status` and increments the study's `version` by 1; this is the ordinary way a project crosses the adequacy boundary in either direction. Studies are listable per project and across the estate, filterable by `method`, `funding_status` and `adoption_status`, and the estate-wide list additionally accepts `conversion_project_id` and `engineering_report_id` so both funding methods can be compared against one report.

**The first-year budget.** The sponsor creates one initial budget per fiscal year, supplying `reserve_study_id`, a non-empty `fiscal_year_label` unique within the project, `annual_operating_expense_cents` (the non-reserve, non-management annual operating expense, never negative) and `expected_conversion_project_version`. Because the budget writes assessment amounts onto units and bumps the parent project, it is guarded against stale reads: if `expected_conversion_project_version` does not match the project's current `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` and HTTP status 412, and nothing is written. A caller whose copy of the project is out of date must re-read the project and retry with the version it then observes. On success the project's `version` is incremented by 1 and the budget is created at `status` `DRAFT`, where `status` holds `DRAFT`, `ADOPTED` or `SUPERSEDED`.

The budget then executes a chain that looks circular and is deliberately not: the management fee is a percentage of the expense base, the tier of that percentage is keyed on the expense base, and the disclosed total includes the fee. The evaluation order is pinned and runs **exactly once**, with no re-tiering pass and no fixed-point iteration. Step one copies `reserve_contribution_cents` from the referenced study's `recommended_annual_contribution_cents`; the study may be at any `adoption_status`, and because the figure is copied at creation a later adjustment of the study does not retroactively move an existing budget. Step two sets `base_expense_cents` to `annual_operating_expense_cents` plus `reserve_contribution_cents`. Step three selects `management_fee_bp` from `base_expense_cents` **and from nothing else**: below 12000000 cents — that is, below one hundred and twenty thousand dollars a year — the tier is 800 basis points; from 12000000 cents inclusive up to but not including 30000000 cents the tier is 650 basis points; at 30000000 cents or above the tier is 500 basis points. The lower bound of each band is inclusive and the upper bound strict, so a base of exactly 12000000 cents takes `650` rather than `800`, and the only values `management_fee_bp` may ever hold are `500`, `650` and `800`. Step four sets `management_fee_cents` to `base_expense_cents` multiplied by `management_fee_bp` divided by 10000, rounded half up to whole cents, computed once. Step five sets `total_annual_expense_cents` to `base_expense_cents` plus `management_fee_cents`.

Step six is a prohibition rather than an action: **there is no re-tiering**. Even when `total_annual_expense_cents` crosses a tier ceiling that `base_expense_cents` did not, `management_fee_bp` and `management_fee_cents` retain the values chosen in steps three and four. A base of 11900000 cents selects 800 basis points, yields a fee of 952000 cents and a total of 12852000 cents; that total sits above the first ceiling, and the tier is nevertheless **not** revised down to 650. Step seven runs the per-unit assessment allocation described below using `total_annual_expense_cents` as the amount to distribute, then sets `assessment_income_cents` to the sum of `unit_annual_assessment_cents` over the project's units whose `declaration_status` is `INCLUDED`; withdrawn units contribute no assessment income. Step eight sets `developer_deficit_funding_cents` to the difference between `total_annual_expense_cents` and `assessment_income_cents`, floored at 0 so the field never goes negative. Step nine sets `developer_subsidy_flag` to true exactly when `developer_deficit_funding_cents` is strictly above 0. While the budget is still `DRAFT` the sponsor may adjust `annual_operating_expense_cents`, and the whole chain is re-derived from scratch including a fresh single-pass tier selection, incrementing the budget's `version` by 1. Budgets are listable per project and across the estate, filterable by `status` and `developer_subsidy_flag`, with `conversion_project_id` and `reserve_study_id` filters on the estate-wide list.

**Allocating the assessment across units.** The allocation population is pinned to the project's units whose `declaration_status` is `INCLUDED`, iterated in ascending `created_at` order throughout, and it uses the effective `percentage_interest_bp` written by the reallocation sweep rather than the declared base. If that set is empty, `assessment_income_cents` is set to 0 and the allocation ends. Otherwise, for each included unit the exact raw share is the total to distribute multiplied by that unit's `percentage_interest_bp` and divided by 10000. **The rounding order is pinned: round per unit first, then sum.** Each unit's raw share is rounded half up to whole cents; those rounded amounts are summed; and the remainder is the total to distribute less that sum, a figure which may be negative when half-up rounding has over-allocated. When the remainder is not 0, the whole remainder is applied to exactly one unit — never spread — chosen by taking the included units ordered by `percentage_interest_bp` descending and breaking ties by `created_at` ascending, and taking the first. Summing the exact shares and rounding the total once is explicitly not the contract and produces a different per-unit split from the same inputs.

Each unit's `unit_annual_assessment_cents` is then written from its adjusted annual amount, and `unit_monthly_assessment_cents` is that already-rounded annual amount divided by 12 and rounded half up — a second, independent rounding. The twelve monthly amounts across the building need not multiply back to the annual total; that drift is intentional and must not be corrected. Every unit of the project whose `declaration_status` is `WITHDRAWN` has both `unit_annual_assessment_cents` and `unit_monthly_assessment_cents` zeroed. The closing invariant is that `assessment_income_cents` equals the total to distribute exactly, because the single-unit residual sweep absorbs all rounding drift. As a worked illustration, a total of 100003 cents across three units holding 3333, 3333 and 3334 basis points gives raw shares of 33331.0, 33331.0 and 33341.0, annual amounts of 33331, 33331 and 33341, an allocated sum of 100003 and a remainder of 0. The same allocation is re-run whenever a unit is withdrawn or reinstated, since both change the `INCLUDED` set and therefore every unit's effective interest.

**Adoption.** The sponsor or a `StateRegulator` adopts a draft budget, moving its `status` `DRAFT → ADOPTED` and stamping `adopted_at` from the logical clock. Adoption is exclusive: any previously `ADOPTED` sibling budget of the project is moved to `SUPERSEDED`, the referenced reserve study's `adoption_status` becomes `ADOPTED`, and the study behind the superseded budget becomes `SUPERSEDED`. The budget's `version` increments by 1. An adopted budget whose study is also adopted is precisely what recording the declaration and conferring statement effectiveness require, and both refuse with `ERR_RESERVE_STUDY_NOT_ADOPTED` (409) when either half of that pair is missing.

### 3.6. Existing Tenants: Statutory Notice, the Right of First Refusal and Relocation Assistance

Every household in occupancy when the conversion begins is registered on the notice register by the sponsor with a non-empty `household_label` unique within the project, a `tenancy_start_date` recording the first day of continuous occupancy, a `monthly_rent_cents` figure of current contract rent that may not be negative, an optional `protected_class` defaulting to `NONE`, and an optional `occupied_unit_id` naming the platted unit occupied. The link to a unit is nullable because households are commonly registered before the plat defines units. `protected_class` holds `NONE`, `HOUSEHOLD_WITH_MINOR`, `ELDERLY` or `DISABLED`.

A household carries **three independent state fields on the same row**, and they must be reasoned about separately. `notice_status` tracks the statutory notice and holds `PRE_NOTICE`, `NOTICE_SERVED`, `VACATE_DUE`, `VACATED`, `HOLDOVER` or `NOTICE_WITHDRAWN`, of which `VACATED`, `HOLDOVER` and `NOTICE_WITHDRAWN` are terminal. `rofr_status` tracks the right of first refusal and holds `NOT_OFFERED`, `OFFERED`, `EXERCISED`, `WAIVED` or `EXPIRED`, of which the last three are terminal. `relocation_status` tracks the money and holds `NOT_OWED`, `ACCRUED`, `PAID` or `REVERSED`, with `REVERSED` terminal. A registered household starts at `PRE_NOTICE`, `NOT_OFFERED` and `NOT_OWED`, with `relocation_assistance_cents` 0 and `version` 1. Households are listable per project and estate-wide, filterable on all three status fields and on `protected_class`, with `conversion_project_id` and `occupied_unit_id` filters on the estate-wide list. While `notice_status` is still `PRE_NOTICE` the sponsor may adjust the pre-notice facts — `monthly_rent_cents`, `tenancy_start_date`, `protected_class` and `occupied_unit_id` — each adjustment incrementing the household's `version` by 1; once notice is served those facts are frozen, because the notice length and the assistance amount were computed from them.

**Serving notice** is the single act that advances all three dimensions at once. The sponsor serves it, taking `notice_status` `PRE_NOTICE → NOTICE_SERVED`, and four preconditions apply: `notice_status` must be `PRE_NOTICE`; the project's declaration package must be at `PLAT_CERTIFIED` or `RECORDED`, since a household cannot be noticed about a regime that has not yet been platted; `occupied_unit_id` must be non-null and the referenced unit must be `INCLUDED` and belong to the same project, refused otherwise with `ERR_ROFR_UNIT_NOT_LINKED` (409); and the project's `posture` must not be `FROZEN`.

The notice length is tiered on completed whole months of tenancy. The elapsed tenancy is the interval from `tenancy_start_date` to the moment of service, divided by 2592000 seconds — a flat thirty-day month, not a calendar month — and floored to a whole number of months. Fewer than 12 completed months gives a base notice of 120 days; from 12 up to but not including 60 months gives 180 days; 60 or more gives 270 days. A protected-class extension is then added, and it is always the **single largest applicable extension and never a sum**: 0 days for `NONE`, 45 days for `HOUSEHOLD_WITH_MINOR`, and 90 days for `ELDERLY` or `DISABLED`. The sum of base and extension is written to `notice_period_days`. From the instant of service, `notice_served_at` is stamped from the logical clock, `vacate_deadline_at` is set to that instant plus `notice_period_days` multiplied by 86400 seconds, and `rofr_expires_at` is set to that same instant plus 90 days, again as an exact multiple of 86400 seconds. No calendar arithmetic and no business-day skipping enter any of these computations.

**The relocation amount is computed in a pinned order of operations**, and the order is the whole substance of the rule. Step one multiplies `monthly_rent_cents` by 3 and rounds half up to whole cents. Step two caps the running amount at 1500000 cents — fifteen thousand dollars. Step three applies an uplift only when `protected_class` is `ELDERLY` or `DISABLED`, multiplying the running amount by 3 and dividing by 2 and rounding half up. Step four applies the 1500000-cent cap **again**. Step five raises the running amount to a floor of 250000 cents — two thousand five hundred dollars — if it sits below it. The result is written to `relocation_assistance_cents`. Because the cap is applied before the uplift and again after it, and because the floor is applied last, the floor can lift a capped amount but the cap can never claw back the floor, and the uplift is observable only for amounts still below the cap. A tenant of 60 months at 900000 cents of monthly rent with no protected class receives 270 notice days and an assistance amount of 1500000 cents, the three-month figure of 2700000 having been capped; an `ELDERLY` tenant at the same rent receives 360 notice days and also exactly 1500000 cents, since the pre-uplift cap had already bound. Only the target household enters this computation: no sibling household, no unit data and no project aggregate participates.

Service also moves `rofr_status` `NOT_OFFERED → OFFERED`, moves `relocation_status` `NOT_OWED → ACCRUED`, adds `relocation_assistance_cents` to both the project's `relocation_obligation_accrued_cents` and its `relocation_outstanding_cents`, recomputes `posture`, and increments the household's `version` by 1.

**The right of first refusal window.** The tenant answers with a `response` of either `EXERCISE` or `WAIVE`, and only the household itself may answer: the caller identity must match the household, and a mismatch is an identity failure. The window is inclusive — the answer is admissible while the logical clock is **at or before** `rofr_expires_at`, so an answer landing exactly on the expiry instant is still inside the window, while one instant later is refused with `ERR_ROFR_WINDOW_EXPIRED` (409). Both answers additionally require `rofr_status` to be `OFFERED`.

The two answers are branch siblings with **disjoint effects**. `WAIVE` moves `rofr_status` `OFFERED → WAIVED` and deliberately leaves `notice_status` and `relocation_status` untouched: the notice clock keeps running and the relocation obligation stands. `EXERCISE` additionally requires that `occupied_unit_id` be non-null and reference an `INCLUDED` unit of the same project, again guarded by `ERR_ROFR_UNIT_NOT_LINKED`, and it cancels the eviction outright — `rofr_status` moves `OFFERED → EXERCISED`, `notice_status` moves `NOTICE_SERVED → NOTICE_WITHDRAWN` with `vacate_deadline_at` cleared to null, and the relocation obligation is reversed. Both answers recompute `posture` and increment the household's `version` by 1. A tenant who has passed the window without answering is caught by the system sweep: a household still at `OFFERED` whose `rofr_expires_at` is **strictly before** the current clock moves `OFFERED → EXPIRED`.

**The vacate deadline and the occupancy outcome.** A household at `NOTICE_SERVED` whose `vacate_deadline_at` is at or before the current clock is moved `NOTICE_SERVED → VACATE_DUE` by the same system sweep; the comparison is inclusive, so the sweep fires on the deadline instant itself. The sponsor then records how the tenancy actually ended by supplying an `outcome`. This is refused with `ERR_NOTICE_PERIOD_NOT_ELAPSED` (409) unless the logical clock has reached `vacate_deadline_at`. An `outcome` of `VACATED` moves `notice_status` `VACATE_DUE → VACATED` and carries the additional precondition that `relocation_status` must already be `PAID` or `REVERSED` — a household cannot be recorded as having moved out while the statutory assistance is still merely accrued. An `outcome` of `HOLDOVER` moves `VACATE_DUE → HOLDOVER` with no money precondition at all, but it recomputes `posture` with consequence: a project with any household in `HOLDOVER` can never evaluate to `OPEN`. That is the whole asymmetry between the two branches — `VACATED` demands settled money and leaves posture alone, `HOLDOVER` demands nothing and gates the posture.

**The relocation ledger is a conserved quantity.** The project carries four ledger fields plus a reconciliation field. `relocation_obligation_accrued_cents` is a monotonic sum of every assistance amount ever accrued and never decreases. `relocation_paid_cents` sums the households' `relocation_paid_cents`. `relocation_reversed_cents` sums the households' `relocation_reversed_cents`. `relocation_outstanding_cents` is the sum of `relocation_assistance_cents` over the households whose `relocation_status` is still `ACCRUED`. And `relocation_reconciliation_delta_cents` is `relocation_obligation_accrued_cents` less the total of `relocation_paid_cents`, `relocation_reversed_cents` and `relocation_outstanding_cents`. **That delta must be exactly 0 after every request, without exception.** Equivalently: everything ever accrued is at every instant either paid, reversed, or still outstanding.

Three edges move money along that ledger. An `EscrowAgent` — and only an `EscrowAgent`, since only escrow disburses cash — pays the assistance, supplying `amount_cents`. The amount must equal the household's `relocation_assistance_cents` **exactly**; any other figure, higher or lower, is refused with `ERR_RELOCATION_AMOUNT_MISMATCH` (422). The household's `relocation_status` must be `ACCRUED` and its `notice_status` must be `NOTICE_SERVED` or `VACATE_DUE`. The payment moves `relocation_status` `ACCRUED → PAID`, writes the household's `relocation_paid_cents`, adds the amount to the project's `relocation_paid_cents` and subtracts the identical amount from `relocation_outstanding_cents`, keeping the delta at 0.

The reversal path is the compensating edge and it restores the conserved quantity exactly. When a tenant exercises the right of first refusal, an accrued-but-unpaid obligation moves `relocation_status` `ACCRUED → REVERSED`, writing the household's `relocation_reversed_cents` from its `relocation_assistance_cents`, adding that amount to the project's `relocation_reversed_cents` and subtracting it from `relocation_outstanding_cents`. An obligation already paid moves `PAID → REVERSED` instead: the household's `relocation_reversed_cents` is set from its `relocation_paid_cents` and its `relocation_paid_cents` is then zeroed, while at project level the recovered amount is subtracted from `relocation_paid_cents` and added to `relocation_reversed_cents`. In both cases the accrued total is untouched — it is monotonic — and the identity holds before and after: the same cents that were outstanding or paid are now reversed, no cents are created, and none are destroyed.

### 3.7. The Public Offering Statement: Statutory Sections, Effectiveness and Amendments

The public offering statement is the disclosure document a purchaser actually receives, and a project may have at most one. The sponsor creates it against the project, naming the `declaration_package_id` whose regime it discloses, the `reserve_study_id` disclosed in the reserves section and the `initial_budget_id` disclosed in the budget section. Creation is a cascade: the statement is born at `status` `DRAFT` with `amendment_count` 0, `complete_section_count` 0, `version` 1, and **nine child sections are synthesized in the same act**, one per statutory `section_code`, each at `content_status` `DRAFTED`. The nine codes are `UNIT_BOUNDARIES`, `COMMON_ELEMENTS`, `PERCENTAGE_INTERESTS`, `BUDGET`, `RESERVES`, `ENGINEERING_CONDITION`, `TENANT_RIGHTS`, `WARRANTY` and `RESCISSION_RIGHTS`, and each code appears exactly once per statement. Every section carries `public_offering_statement_id` back to its parent. The `status` field of the statement holds `DRAFT`, `SECTIONS_COMPLETE`, `EFFECTIVE`, `AMENDMENT_REQUIRED` or `AMENDMENT_FILED`, and none of those five is terminal — the amendment cycle can be entered and left without bound. Statements are listable per project and estate-wide, filterable by `status`, with `conversion_project_id`, `declaration_package_id`, `reserve_study_id` and `initial_budget_id` filters on the estate-wide list. The synthesized sections are discoverable only through the statement's own section listing, which is filterable by `content_status` and `section_code`, and a single section is addressable by its `section_code`.

**Drafting a section** is an idempotent write addressed by `section_code`. The sponsor supplies a non-empty `body_ref` storage reference for the drafted body, a `word_count` of the drafted length which may not be negative, and optionally an `attested_by_user_id` — the identity of the sponsor attesting the content. `content_status` is then recomputed rather than set: it becomes `COMPLETE` only when `body_ref` is present, `word_count` is **at or above** 150 words, and `attested_by_user_id` has been supplied; otherwise it becomes `DRAFTED`. A section of exactly 150 attested words is therefore `COMPLETE` while one of 149 is not, and an unattested section of any length remains `DRAFTED`. Because `body_ref` is a required input, `content_status` only ever holds one of its two declared members. When attestation is supplied, `last_attested_at` is stamped from the logical clock. The parent's `complete_section_count` is recomputed as the number of child sections at `COMPLETE`, and the section's `version` increments by 1.

That recount drives a **bubble in both directions**, applied by the system rather than requested. When the statement is at `DRAFT` and the write leaves `complete_section_count` at exactly 9 — every one of the nine statutory codes `COMPLETE` — the statement moves `DRAFT → SECTIONS_COMPLETE` and its `version` increments by 1. When the statement is at `SECTIONS_COMPLETE` and the write leaves `complete_section_count` below 9 — for instance because a section was rewritten with a shorter body or without attestation — the statement bubbles back `SECTIONS_COMPLETE → DRAFT`, again incrementing its `version`. Rewriting a completed section is therefore a way to un-complete the whole statement, and the pair closes a cycle that may be traversed repeatedly.

**Conferring effectiveness** is reserved to the `StateRegulator` alone; no sponsor, engineer or escrow role may confer it, because effectiveness is the state's act of registration. The regulator can confer it from either of two states. The first is `SECTIONS_COMPLETE → EFFECTIVE`, on which four preconditions apply: the statement is at `SECTIONS_COMPLETE`; the declaration package named by `declaration_package_id` has `status` `RECORDED`, refused otherwise with `ERR_DECLARATION_NOT_RECORDED` (409); the budget named by `initial_budget_id` has `status` `ADOPTED` and its referenced reserve study has `adoption_status` `ADOPTED`, refused otherwise with `ERR_RESERVE_STUDY_NOT_ADOPTED` (409); and the project's `posture` is not `FROZEN`. A statement whose `complete_section_count` is below 9 is refused with `ERR_POS_SECTIONS_INCOMPLETE` (409). Effectiveness sets `status` to `EFFECTIVE`, stamps `effective_at` from the logical clock, moves the project `REGISTRATION → PRESALE`, recomputes `posture` — which is how a project first becomes eligible to read `OPEN` — and increments the statement's `version` by 1. The second is `AMENDMENT_FILED → EFFECTIVE`, which closes the amendment round: the preconditions are that the statement is at `AMENDMENT_FILED`, that `complete_section_count` is exactly 9, that `posture` is not `FROZEN`, and that the declaration package is `RECORDED`; the side effects are identical, including the `REGISTRATION → PRESALE` advance and a fresh `effective_at`. Because `effective_at` records the **most recent** entry into `EFFECTIVE`, a statement that has been through amendment rounds carries a later `effective_at` than its first registration.

**When the disclosure goes stale by itself.** The `EFFECTIVE → AMENDMENT_REQUIRED` edge is driven by the system, never requested. It fires when a statement is `EFFECTIVE` and either the project's `suitability_gate` became `FAILED` in the same request — the peer-review rejection cascade — or a unit of the project moved `declaration_status` from `INCLUDED` to `WITHDRAWN` in the same request. Either event makes the document materially untrue about the building or about the units on offer, so the statement is marked as needing amendment and its `version` increments by 1. The project cannot sell against a statement in that state: any attempt to write a purchase agreement or to deliver the statement to a purchaser is refused with `ERR_POS_NOT_EFFECTIVE` (409).

**Filing an amendment.** The sponsor files an amendment against a statement at `EFFECTIVE` or at `AMENDMENT_REQUIRED`, supplying a `material_change` boolean and an `amendment_summary`. Both edges — `EFFECTIVE → AMENDMENT_FILED` and `AMENDMENT_REQUIRED → AMENDMENT_FILED` — land on `AMENDMENT_FILED`, and both increment `amendment_count` by 1, which records the amendment round number; amendment rounds are unbounded. With `material_change` false, that is the whole effect: `amendment_count` moves, `posture` is recomputed, the statement's `version` increments, and **no purchase agreement and no batch is disturbed**. The document has changed in a way that does not reopen anybody's rescission right.

With `material_change` true, filing is hop one of a **four-hop cascade**, and each hop is caused by the one before it. Hop one sets `status` to `AMENDMENT_FILED`, increments `amendment_count` by 1, and writes `last_material_amendment_at` from the logical clock. Hop two is caused by that `last_material_amendment_at` write: the population is the project's purchase agreements whose `contract_status` is `SIGNED` or `HARD` and whose `pos_delivered_at` is non-null, taken in ascending `created_at` order. Every agreement in that population at `HARD` reverts `HARD → SIGNED`, so the revived rescission right is actually exercisable, and every agreement in the population has its `rescission_deadline_at` recomputed under the restart clause with `rescission_restart_count` incremented by 1. Agreements at `CLOSED`, `RESCINDED` or `VOID` are never restarted — a closed sale is not reopened by an amendment. The restart clause sets `rescission_deadline_at` to the later of its current value and the amendment instant plus 5 days, expressed as an exact multiple of 86400 seconds, so a restart **never shortens** a deadline that was already further out.

Hop three is caused by hop two removing those agreements from the hardened population: every closing batch of the project whose recomputed presale percentage falls below its `min_presale_threshold_pct`, or whose recomputed `qualifying_agreement_count` falls below its `min_absolute_unit_count`, and whose `status` is `THRESHOLD_MET` or `RELEASED`, moves to `THRESHOLD_SHORT`. Hop four is caused by hop three: for a batch that left `RELEASED`, the project moves `CLOSINGS → PRESALE`; and because the statement itself has left `EFFECTIVE`, the project additionally moves `PRESALE → REGISTRATION` with `posture` recomputed to `RESTRICTED`. A project mid-closings therefore falls all the way back to registration on a single material amendment, and it climbs out only by the regulator conferring effectiveness again, which requires all nine sections still `COMPLETE`, the package still `RECORDED` and the project not `FROZEN`. Filing against an `AMENDMENT_REQUIRED` statement applies exactly the same hop two, hop three and hop four chain when `material_change` is true.

### 3.8. Selling Units: Contracts, Escrow, the Rescission Window and Lender Warrantability

A purchase agreement is signed against a single unit by the sponsor or by a `Purchaser`, and it is the busiest object in the system. Its inputs are a non-empty `purchaser_name`, a non-empty `purchaser_tax_id` used to aggregate single-investor concentration, a `purchaser_type` of either `OWNER_OCCUPANT` or `INVESTOR`, a `price_cents` of at least 1, a `deposit_cents` between 0 and `price_cents` inclusive, an optional `tenant_household_id` set when the purchaser is the sitting tenant buying under its right of first refusal, and `expected_unit_version`. Because signing rewrites the unit's `sale_status`, the operation is guarded against stale reads of the unit: when `expected_unit_version` does not match the unit's current `version`, the request is rejected with `ERR_STALE_UNIT_VERSION` and HTTP status 412 and nothing is written. On success the unit's `version` is incremented by 1. The unit must be `INCLUDED` and the project must have a statement at `EFFECTIVE`, refused otherwise with `ERR_POS_NOT_EFFECTIVE` (409). The agreement copies `conversion_project_id` from the unit and `public_offering_statement_id` from that effective statement, stamps `signed_at` from the logical clock, and starts at `contract_status` `SIGNED`, `escrow_status` `PENDING`, `closing_batch_id` null, `pos_delivered_at` null, `rescission_deadline_at` null, `rescission_restart_count` 0 and `closed_at` null; the unit's `sale_status` moves `UNSOLD → UNDER_CONTRACT`.

Like a household, an agreement carries **two independent state fields**. `contract_status` holds `SIGNED`, `HARD`, `CLOSED`, `RESCINDED` or `VOID`, of which the last three are terminal. `escrow_status` holds `PENDING`, `FUNDED`, `REFUNDED` or `DISBURSED`, of which `REFUNDED` and `DISBURSED` are terminal. Agreements are listable under their unit and estate-wide, filterable by `contract_status` and `escrow_status`, with `conversion_project_id`, `unit_id`, `public_offering_statement_id`, `closing_batch_id`, `tenant_household_id` and `purchaser_type` filters on the estate-wide list. While `contract_status` is `SIGNED` and `escrow_status` is `PENDING`, the sponsor may adjust `purchaser_name`, `purchaser_tax_id`, `purchaser_type`, `price_cents` and `deposit_cents`, which recomputes the project's warrantability ratios under the contract basis and increments the agreement's `version` by 1. Changing `purchaser_type` changes which rescission window a later delivery will select, but it does **not** by itself restart an already-computed `rescission_deadline_at`.

**Delivering the statement starts the rescission clock.** The sponsor records delivery of the effective statement to the purchaser, which stamps `pos_delivered_at` from the logical clock and computes `rescission_deadline_at` as that instant plus a window that depends entirely on `purchaser_type`: 15 days for an `OWNER_OCCUPANT`, 7 days for an `INVESTOR`, each expressed as an exact multiple of 86400 seconds with no calendar or business-day arithmetic. An investor contract delivered at the same instant as an owner-occupant contract therefore becomes hardenable eight days earlier. The agreement's `version` increments by 1.

**The boundary at the deadline is deliberately asymmetric, and it is the single most exacting comparator in the system.** Rescission is permitted while the logical clock is **strictly before** `rescission_deadline_at`; hardening is permitted while the clock is **at or after** it. At the exact deadline instant the two rules do not overlap and do not leave a gap: rescission is refused with `ERR_RESCISSION_PERIOD_CLOSED` (409) and hardening succeeds. One instant earlier, rescission succeeds and hardening is refused with `ERR_RESCISSION_PERIOD_OPEN` (409). Both operations additionally require `pos_delivered_at` to be non-null, refused otherwise with `ERR_POS_NOT_DELIVERED` (409), because neither a rescission right nor its expiry exists before the purchaser has actually received the disclosure.

**Funding escrow.** An `EscrowAgent` — and only an `EscrowAgent` — funds the earnest deposit, supplying `amount_cents` which must equal the agreement's `deposit_cents` **exactly**; any other figure is refused with `ERR_ESCROW_AMOUNT_MISMATCH` (422). The agreement must be at `escrow_status` `PENDING` and `contract_status` `SIGNED`. Funding moves `escrow_status` `PENDING → FUNDED`, adds `deposit_cents` to both the project's `escrow_balance_cents` and its `escrow_deposits_received_cents`, recomputes the assigned batch's `qualifying_agreement_count` and `presale_pct` if the agreement has been assigned, and increments the agreement's `version` by 1.

**Hardening.** The sponsor or an `EscrowAgent` hardens a contract once the rescission period has closed, moving `contract_status` `SIGNED → HARD`. Five preconditions apply: `contract_status` is `SIGNED`; `pos_delivered_at` is non-null; the clock is at or after `rescission_deadline_at`; `escrow_status` is `FUNDED`, refused otherwise with `ERR_ESCROW_NOT_FUNDED` and HTTP status 402 — a payment-required refusal, since the money is genuinely absent rather than the request being malformed; and the project's `posture` is not `FROZEN`. Hardening moves the unit's `sale_status` `UNDER_CONTRACT → HARD_CONTRACT`, recomputes the assigned batch's `qualifying_agreement_count` and `presale_pct`, and a batch at `THRESHOLD_SHORT` that now satisfies both of its thresholds is carried to `THRESHOLD_MET`. The warrantability ratios are recomputed under the contract basis and the agreement's `version` increments by 1.

**Rescinding.** The purchaser — whose identity must match the agreement — or the sponsor acting for that purchaser exercises the statutory rescission right strictly before the deadline, optionally recording a `rescission_reason`. The agreement must be at `contract_status` `SIGNED`, which is why the material-amendment cascade must first revert a hardened contract to `SIGNED` before the revived right is exercisable. Rescission is a four-hop cascade. Hop one takes `contract_status` `SIGNED → RESCINDED` and moves `escrow_status` `FUNDED → REFUNDED`, a no-op when escrow was still `PENDING` and no cash had been taken. Hop two, caused by the escrow status leaving `FUNDED`, subtracts `deposit_cents` from the project's `escrow_balance_cents`, adds the identical amount to `escrow_refunded_cents`, and recomputes the unit's `sale_status` to `UNSOLD` because the unit no longer has any agreement at `SIGNED`, `HARD` or `CLOSED`. Hop three, caused by hop two removing the agreement from the qualifying population, recomputes the assigned batch's `qualifying_agreement_count` and `presale_pct`; when the recomputed `presale_pct` falls below `min_presale_threshold_pct` or `qualifying_agreement_count` falls below `min_absolute_unit_count` and the batch reads `THRESHOLD_MET` or `RELEASED`, the batch moves to `THRESHOLD_SHORT`. Hop four, caused by hop three for a batch that left `RELEASED`, moves the project `CLOSINGS → PRESALE` and recomputes `posture` to `RESTRICTED`. The warrantability ratios are recomputed and the agreement's `version` increments by 1.

**Escrow cash is a conserved quantity.** The project maintains `escrow_deposits_received_cents` as the monotonic total of every deposit ever funded, `escrow_balance_cents` as the cash currently held, `escrow_refunded_cents` as the cash returned to purchasers, and `escrow_disbursed_cents` as the cash released at closing. The reconciliation field `escrow_reconciliation_delta_cents` is `escrow_deposits_received_cents` less the total of `escrow_balance_cents`, `escrow_refunded_cents` and `escrow_disbursed_cents`, and **it must be exactly 0 after every request**. Every cent ever received is at every instant either held, refunded or disbursed; no cent is in two buckets and none is in none. Agreements still at `escrow_status` `PENDING` contribute to no bucket at all and are excluded from `escrow_deposits_received_cents` until they reach `FUNDED`. The compensating pair of funding followed by refund therefore leaves `escrow_balance_cents` where it began while `escrow_deposits_received_cents` and `escrow_refunded_cents` both rise by the deposit — the delta stays 0 throughout. These identities are exact integer arithmetic and are never rounded.

**Lender warrantability.** A `LenderUnderwriter`, the sponsor, a `StateRegulator` or a `PlatformAdmin` may read the project's warrantability summary, and that read is not passive: it runs the ratio computation under **both** bases and persists both verdicts on the project. The two bases differ only in their population. The contract basis — the lender's pre-closing view — counts the project's agreements whose `contract_status` is `SIGNED`, `HARD` or `CLOSED`. The closed basis — the lender's funded view — counts only agreements at `CLOSED`. Agreements at `RESCINDED` or `VOID` are excluded from both. When the selected population is empty the pinned fallback applies: `owner_occupancy_pct_contract_basis` or its closed-basis counterpart, `investor_concentration_pct_contract_basis` or its counterpart, `single_investor_max_pct` and `presale_sold_pct` are all set to 0.00, and the verdict is `NON_WARRANTABLE` on the ground that there are no qualifying contracts at all.

Otherwise the denominator is the count of agreements in the selected population. `owner_occupancy_pct_contract_basis` is 100 multiplied by the count of contract-basis agreements at `purchaser_type` `OWNER_OCCUPANT`, divided by that denominator, rounded half up to 2 decimal places; `investor_concentration_pct_contract_basis` is the same computation over agreements at `INVESTOR`. The closed-basis run writes `owner_occupancy_pct_closed_basis` and `investor_concentration_pct_closed_basis` from the closed-only population. Every percentage is computed once from exact integer counts and never from a previously rounded percentage. `single_investor_max_pct` behaves differently from all of them: it groups the **contract-basis** agreements by `purchaser_tax_id` regardless of which basis is being reported, takes the largest group size, multiplies by 100 and divides by the project's `total_unit_count` — the as-declared count, never `included_unit_count` — rounded half up to 2 decimal places. `presale_sold_pct` is 100 multiplied by the count of `INCLUDED` units whose `sale_status` is `HARD_CONTRACT` or `SOLD`, divided by the count of `INCLUDED` units, rounded half up to 2 decimal places, or 0.00 when no unit is included.

The verdict requires **every** clause to hold, and each boundary is inclusive on the favourable side: owner occupancy at or above 50.00 percent, investor concentration at or below 25.00 percent, single-investor concentration at or below 10.00 percent, and presale sold at or above 51.00 percent. A project sitting at exactly 50.00 percent owner occupancy and exactly 25.00 percent investor concentration is `WARRANTABLE` on those clauses. The result is written to `warrantability_verdict` for the contract-basis run and to `warrantability_verdict_closed_basis` for the closed-basis run, each holding `UNEVALUATED`, `WARRANTABLE` or `NON_WARRANTABLE` and each defaulting to `UNEVALUATED` before any run. **The two verdicts are persisted separately and routinely disagree on the identical agreement book.** Two closed investor contracts plus three signed owner-occupant contracts give contract-basis figures of 60.00 and 40.00 against closed-basis figures of 0.00 and 100.00 — both `NON_WARRANTABLE`, but for different reasons, the first failing the investor clause and the second the occupancy clause. Three closed owner-occupant contracts plus three signed investor contracts give contract-basis 50.00 and 50.00 against closed-basis 100.00 and 0.00. The ratios are also recomputed as a side effect whenever an agreement is signed, adjusted, hardened or rescinded — those runs under the contract basis — and whenever an agreement closes, that run under the closed basis.

### 3.9. Closing Batches, Release Sequencing, Project Completion and Common-Element Warranty Claims

Closings are sequenced through batches. The sponsor creates a batch on a project with a `batch_sequence_no` between 1 and 50 inclusive and unique within the project, a `window_start_at` and a `window_end_at` bounding the settlement window, a `min_presale_threshold_pct` between 0.00 and 100.00 inclusive carried to 2 decimal places, and a `min_absolute_unit_count` of at least 0 which defaults to 1. A new batch starts at `status` `DRAFT` with `assigned_agreement_count` 0, `qualifying_agreement_count` 0, `presale_pct` 0.00, `released_at` null and `last_evaluated_at` null. `status` holds `DRAFT`, `OPEN_FOR_ASSIGNMENT`, `THRESHOLD_SHORT`, `THRESHOLD_MET`, `RELEASED` or `SETTLED`, of which only `SETTLED` is terminal. Batches are listable per project, filterable by `status`.

**The settlement window is half-open, and adjacency is allowed.** The window covers `window_start_at` inclusively and stops strictly short of `window_end_at`. `window_end_at` must be strictly after `window_start_at`, so a zero-length or inverted window is rejected. The requested window may not overlap the window of any sibling batch of the same project whose `status` is `DRAFT`, `OPEN_FOR_ASSIGNMENT`, `THRESHOLD_SHORT`, `THRESHOLD_MET` or `RELEASED`; a batch at `SETTLED` no longer occupies its window. Two windows overlap exactly when the new start falls strictly before the other's end **and** the other's start falls strictly before the new end. Because both comparisons are strict, a new window starting at precisely the instant a sibling window ends is **accepted**: there is no buffer, no gap requirement, and no aggregate capacity beyond the rule that at most one batch may occupy any single instant. A genuine overlap is refused with `ERR_BATCH_WINDOW_OVERLAP` (409). While a batch is at `DRAFT`, `OPEN_FOR_ASSIGNMENT`, `THRESHOLD_SHORT` or `THRESHOLD_MET` the sponsor may adjust `window_start_at`, `window_end_at`, `min_presale_threshold_pct` and `min_absolute_unit_count`, and window edits are re-checked against the identical overlap rule; threshold edits by themselves do **not** re-evaluate the batch, which requires an explicit evaluation.

**Assigning agreements.** The sponsor or an `EscrowAgent` assigns an agreement to a batch, supplying `purchase_agreement_id` and `expected_closing_batch_version`. The assignment is guarded against stale reads of the batch: a mismatch between `expected_closing_batch_version` and the batch's current `version` is rejected with `ERR_STALE_BATCH_VERSION` and HTTP status 412, leaving the batch and the agreement untouched. The agreement's `conversion_project_id` must match the batch's, and its `closing_batch_id` must be null — an agreement already assigned anywhere is refused with `ERR_AGREEMENT_ALREADY_ASSIGNED` (409). The first assignment carries the batch `DRAFT → OPEN_FOR_ASSIGNMENT`, sets the agreement's `closing_batch_id` to the batch, increments `assigned_agreement_count` by 1, recomputes `qualifying_agreement_count` and `presale_pct`, and increments the batch's `version` by 1. The sponsor may also unassign an agreement from a batch that has not been released, clearing `closing_batch_id`, re-deriving both counters, and moving the batch from `THRESHOLD_MET` to `THRESHOLD_SHORT` when it no longer qualifies — which is how a batch can lose its threshold without anybody rescinding anything. The batch's assigned agreements are listable, filterable by `contract_status` and `escrow_status`.

**Evaluating the presale threshold.** The sponsor, an `EscrowAgent` or a `StateRegulator` runs the evaluation. `assigned_agreement_count` is the count of agreements whose `closing_batch_id` is this batch, at any `contract_status`. `qualifying_agreement_count` is narrower: it counts the assigned agreements whose `contract_status` is `SIGNED`, `HARD` or `CLOSED` **and** whose `escrow_status` is `FUNDED` or `DISBURSED`, so an unfunded contract is assigned but does not qualify. The denominator is the project's count of `INCLUDED` units at evaluation time — never `total_unit_count` and never the assigned count — and when no unit is `INCLUDED` the evaluation is refused outright with `ERR_NO_INCLUDED_UNITS` (409) rather than defaulting to any percentage. `presale_pct` is 100 multiplied by `qualifying_agreement_count`, divided by that included-unit count, rounded half up to 2 decimal places, and `last_evaluated_at` is stamped from the logical clock.

**Both threshold clauses are inclusive.** The batch is met when `presale_pct` is **at or above** `min_presale_threshold_pct` and `qualifying_agreement_count` is **at or above** `min_absolute_unit_count`; the percentage comparison is made on the rounded value, not on the exact ratio. Twenty-six qualifying agreements over 51 included units gives a `presale_pct` of 50.98, which does **not** meet a 51.00 threshold; twenty-seven over 51 gives 52.94, which does; and 51 qualifying agreements over 100 included units gives exactly 51.00, which **does** meet a 51.00 threshold. An evaluation from `OPEN_FOR_ASSIGNMENT` requires the project's `included_unit_count` to be at least 1 and takes the batch `OPEN_FOR_ASSIGNMENT → THRESHOLD_MET` when met and `OPEN_FOR_ASSIGNMENT → THRESHOLD_SHORT` when not, writing `presale_pct` and `last_evaluated_at` and incrementing the batch's `version` by 1; the short branch additionally recomputes the project's `posture`, and a project with any batch at `THRESHOLD_SHORT` can never evaluate to `OPEN`. The project's `presale_sold_pct` is recomputed as well. A batch may also be inspected through a threshold summary read that reports `presale_pct`, `qualifying_agreement_count`, `assigned_agreement_count`, both minimum thresholds and a boolean met flag **without** mutating `status`, which allows the inclusive boundary to be examined before committing to an evaluation.

The batch oscillates freely between the two threshold states. A batch at `THRESHOLD_SHORT` that now satisfies both clauses moves `THRESHOLD_SHORT → THRESHOLD_MET`, either on an explicit evaluation or as a system consequence of an agreement hardening, recomputing `posture` on the way. A batch at `THRESHOLD_MET` that stops satisfying either clause moves `THRESHOLD_MET → THRESHOLD_SHORT`, triggered by a rescission, by a unit withdrawal, or by a material amendment, and that edge recomputes `posture` to `RESTRICTED`. The pair closes a cycle that may be traversed any number of times.

**Releasing a batch for closing** is reserved to the `EscrowAgent`, and it is the narrowest gate in the sales pipeline. The batch must be at `THRESHOLD_MET`; the project's declaration package must be `RECORDED`, refused otherwise with `ERR_DECLARATION_NOT_RECORDED` (409); the project's statement must be `EFFECTIVE`; **every** assigned agreement must be at `contract_status` `HARD` or `CLOSED`; the project's `posture` must be exactly `OPEN`, not merely un-frozen; and **no other batch of the project may already be at `RELEASED`**, so releases are strictly serialised one batch at a time. A batch that has not met both threshold clauses, or that still holds a merely `SIGNED` agreement, is refused with `ERR_PRESALE_THRESHOLD_NOT_MET` (409). Release takes the batch `THRESHOLD_MET → RELEASED`, stamps `released_at` from the logical clock, moves the project `PRESALE → CLOSINGS`, recomputes `posture` and increments the batch's `version` by 1. The reverse edge exists: a released batch that stops meeting its threshold after a rescission or a material amendment moves `RELEASED → THRESHOLD_SHORT`, has `released_at` cleared back to null, and drags the project `CLOSINGS → PRESALE` with `posture` recomputed to `RESTRICTED`.

**Closing a sale** is likewise the `EscrowAgent`'s act alone, since it disburses money. Seven preconditions apply: the agreement is at `contract_status` `HARD`; its `closing_batch_id` is non-null; the assigned batch is at `RELEASED`, refused otherwise with `ERR_BATCH_NOT_RELEASED` (409); the logical clock lies inside the batch's half-open window, meaning at or after `window_start_at` and **strictly before** `window_end_at`, so a closing attempted at the exact `window_end_at` instant is outside the window; `escrow_status` is `FUNDED`, refused otherwise with `ERR_ESCROW_NOT_FUNDED` (402); the declaration package is `RECORDED`; and `posture` is not `FROZEN`. Closing takes `contract_status` `HARD → CLOSED` and stamps `closed_at`, moves `escrow_status` `FUNDED → DISBURSED` while subtracting `deposit_cents` from `escrow_balance_cents` and adding the identical amount to `escrow_disbursed_cents`, sets the unit's `sale_status` to `SOLD`, recomputes the warrantability ratios under the closed basis, and increments the agreement's `version` by 1.

That closing then bubbles upward. When every unit of the project whose `declaration_status` is `INCLUDED` reads `sale_status` `SOLD`, the project moves `CLOSINGS → COMPLETED` and, as a consequence of that project transition, every batch of the project still at `RELEASED` moves `RELEASED → SETTLED`, its terminal state. `COMPLETED` is the terminal state of the project's `status` dimension. A single withdrawn unit is not an obstacle, because withdrawn units are excluded from the test; an unsold included unit is.

**Common-element warranty claims.** The warranty clock starts at recording. A unit owner's claim is filed against the project by naming the `major_component_id` of the common-element component alleged to be defective, the `reported_by_unit_id` whose owner reported it, a non-empty `defect_description` of at most 500 characters, and a `claimed_cost_cents` estimate of at least 0. Filing requires the project's declaration package to be `RECORDED`, refused otherwise with `ERR_DECLARATION_NOT_RECORDED` (409), because before recording there is no warranty and no common element to warrant. The claim's `warranty_expires_at` is pinned at filing from the project's `warranty_start_at` — which equals `declaration_recorded_at` — plus a window selected entirely by the component's `is_structural` flag: 60 months for a structural component and 24 months for a non-structural one, each month being exactly 2592000 seconds, so the structural window is 155520000 seconds and the non-structural window 62208000 seconds from the recording instant. **The expiry comparison is inclusive**: a claim is admissible while the logical clock is at or before `warranty_expires_at`, and one instant past it the filing, triage or reopening is refused with `ERR_WARRANTY_PERIOD_EXPIRED` (409).

A filed claim starts at `status` `SUBMITTED` with `triage_outcome` `PENDING`, `accrued_charge_cents` 0, `reopen_count` 0, both remediation bounds null, `reported_at` stamped from the clock and `version` 1. `status` holds `SUBMITTED`, `TRIAGED_ADMISSIBLE`, `DENIED`, `REMEDIATION_SCHEDULED`, `REMEDIATED`, `REOPENED` or `CLOSED`, of which `DENIED` and `CLOSED` are terminal; `triage_outcome` holds `PENDING`, `ADMISSIBLE` or `DENIED`. Claims are listable per project and estate-wide, filterable by `status` and `triage_outcome`, with `conversion_project_id`, `major_component_id` and `reported_by_unit_id` filters on the estate-wide list — filtering by component is how the closed remediation windows a new schedule must clear are inspected. A warranty summary read reports `warranty_reserve_charge_cents` together with the per-claim `accrued_charge_cents` breakdown and, for a requested closed window given by `window_start_at` and `window_end_at`, the maximum remediation overlap depth measured against `max_overlapping_remediations`.

**Triage is a fork with disjoint effects.** A `LicensedEngineer` or the sponsor supplies a `decision` of `ADMIT` or `DENY` and an optional `triage_note`. The `SUBMITTED → TRIAGED_ADMISSIBLE` edge under an `ADMIT` decision requires the claim to be `SUBMITTED`, the clock to be at or before `warranty_expires_at`, and the unit at `reported_by_unit_id` to have `sale_status` `SOLD` — only an actual owner has a warranty. It sets `status` to `TRIAGED_ADMISSIBLE` and `triage_outcome` to `ADMISSIBLE`, and accrues the charge: the component cap is the component's `replacement_cost_cents` multiplied by 6000 basis points and divided by 10000, rounded half up — sixty percent of replacement cost — and `accrued_charge_cents` is set to the lesser of `claimed_cost_cents` and that cap, then added to the project's `warranty_reserve_charge_cents`. The `SUBMITTED → DENIED` edge under a `DENY` decision requires only that the claim be `SUBMITTED`: it sets `status` to `DENIED`, sets `triage_outcome` to `DENIED`, leaves `accrued_charge_cents` at 0, **never touches the project's warranty charge ledger**, and applies no unit-sale check at all. Both branches recompute `posture` and increment the claim's `version` by 1.

**Scheduling remediation** is the sponsor's act, supplying `remediation_start_at` and `remediation_end_at`, and it moves the claim `TRIAGED_ADMISSIBLE → REMEDIATION_SCHEDULED`. Its window geometry is deliberately **unlike** the closing-batch rule. The remediation window is a **closed** interval: both endpoints are occupied. `remediation_end_at` must be at or after `remediation_start_at`, so a single-instant window is legitimate. Two tests then run, and the order between them is pinned.

The first is a pairwise test against the other claims on the **same** `major_component_id` whose `status` is `REMEDIATION_SCHEDULED` or `REMEDIATED` and whose `remediation_start_at` is non-null; claims at `SUBMITTED`, `TRIAGED_ADMISSIBLE`, `REOPENED`, `DENIED` or `CLOSED` occupy nothing. A cooldown of 259200 seconds — exactly 72 hours — is added to each existing window's tail. The requested window collides with an existing one when the requested start falls at or before the existing end plus the cooldown **and** the existing start falls at or before the requested end plus the cooldown. Both comparisons are inclusive, so touching endpoints collide — a window beginning at the exact instant another ends is a collision, not adjacency — and a gap of exactly 259200 seconds **still collides**. The earliest admissible start on the same component is the existing end plus 259200 seconds plus one second. A collision is refused with `ERR_REMEDIATION_WINDOW_OVERLAP` (409).

The second test, which runs only after the first has passed, is a project-wide capacity check with no cooldown. Over the requested window and every project window whose claim is at `REMEDIATION_SCHEDULED` or `REMEDIATED`, the endpoint events are ordered by instant ascending with starts placed before ends at the same instant, **so an instant shared by one window's end and another's start counts both windows**. At no instant inside the requested closed window may the resulting depth exceed the project's `max_overlapping_remediations`, whose default is 2 and whose permitted range is 1 through 5; equivalently, the depth must never reach that cap plus one. Breaching it is refused with `ERR_REMEDIATION_CAPACITY_EXCEEDED` (409). A project at the default cap therefore tolerates two remediations covering a shared instant but refuses a third, and lowering the cap to 1 makes any shared instant fatal. Scheduling stores both bounds and increments the claim's `version` by 1.

**Completion, reopening and closure.** The sponsor or a `LicensedEngineer` records completion, moving `REMEDIATION_SCHEDULED → REMEDIATED`, and the clock must be **strictly after** `remediation_end_at`: the closed window must lie wholly in the past, so completion at the exact end instant is premature. An optional `completion_note` may accompany it, and `posture` is recomputed. When the defect recurs, the sponsor or a `Purchaser` reopens the claim with an optional `reopen_reason`, moving `REMEDIATED → REOPENED`. Reopening requires the clock to be at or before `warranty_expires_at` and requires `reopen_count` to be **strictly below 2**, so the third reopening is refused with `ERR_CLAIM_REOPEN_LIMIT_REACHED` (409) — a claim may be reopened twice and no more. Reopening increments `reopen_count` by 1 and clears both `remediation_start_at` and `remediation_end_at` to null, which releases the component's window occupation and frees that interval for another claim.

A reopened claim is triaged again, moving `REOPENED → TRIAGED_ADMISSIBLE` on an `ADMIT` decision while the clock is at or before `warranty_expires_at`; this closes the bounded cycle from `TRIAGED_ADMISSIBLE` through `REMEDIATION_SCHEDULED`, `REMEDIATED` and `REOPENED` and back. The reopen admission applies the **uplift before the cap**: the uplift is the current `accrued_charge_cents` multiplied by 2500 basis points divided by 10000, rounded half up — an additional twenty-five percent — the new total is the lesser of the current charge plus that uplift and the same sixty-percent component cap, and only the **delta** between the new total and the old is added to the project's `warranty_reserve_charge_cents`, so the ledger is never double-counted. A claim already sitting at the cap therefore accrues a delta of 0 on reopening. Finally, the system sweep closes stale claims: a claim at `REMEDIATED` whose `warranty_expires_at` is **strictly before** the current clock moves `REMEDIATED → CLOSED`, its terminal state, and can never be reopened again.

## 4. Endpoint Definitions

Status codes follow one rule throughout the registry API. An operation that mints a brand-new resource — a conversion project, an engineering report, a major component, a suitability assessment, a declaration package, a unit, a public offering statement, an amendment, a tenant household, a notice, a right-of-first-refusal response, a relocation disbursement, an occupancy outcome, a reserve study, an initial budget, a closing batch, an agreement assignment, a purchase agreement, a statement delivery, an escrow deposit or a warranty claim — answers with **201 Created**. Every other successful call answers with **200 OK**: all read endpoints and computed summary reads, every `PATCH` adjustment, the `PUT` that writes a statutory section, every lifecycle transition (submit, peer-review decision, revision, verification, plat certification, recording, withdrawal, reinstatement, effectiveness, budget adoption, threshold evaluation, batch release, hardening, rescission, closing, triage, remediation scheduling, completion, reopening), the posture-recalculation sweep, and the logical-clock endpoints. No endpoint in this API returns **204 No Content** — the single `DELETE` (unassigning an agreement from a closing batch) also answers **200 OK** with a body. Every response, successful or failed, is wrapped in the standard envelope described in §2, so the HTTP status above is always accompanied by the envelope's own `success` flag and `meta` block. Error status codes are not listed in this table; they are catalogued in §5, and the conditions that trigger them are described in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Sets the server's logical current UTC instant used by every temporal rule. | PlatformAdmin, ConverterSponsor, StateRegulator, EscrowAgent, LenderUnderwriter |
| GET | `/_clock/current` | Returns the logical clock's current UTC instant. | PlatformAdmin, ConverterSponsor, StateRegulator, EscrowAgent, LenderUnderwriter, LicensedEngineer, PeerReviewEngineer, TenantOccupant, Purchaser |
| POST | `/conversion-projects` | Creates a conversion project at the start of its feasibility lifecycle. | ConverterSponsor |
| GET | `/conversion-projects` | Lists conversion projects with optional status, posture, gate and sponsor filters. | ConverterSponsor, StateRegulator, LenderUnderwriter, EscrowAgent, PlatformAdmin |
| GET | `/conversion-projects/{id}` | Returns one conversion project with its derived aggregates and verdicts. | ConverterSponsor, StateRegulator, LenderUnderwriter, EscrowAgent, PlatformAdmin, LicensedEngineer, PeerReviewEngineer |
| PATCH | `/conversion-projects/{id}` | Updates a conversion project's mutable inputs. | ConverterSponsor, PlatformAdmin |
| POST | `/conversion-projects/{id}/posture-recalculations` | Runs the explicit expiry-and-posture sweep against the current logical clock. | ConverterSponsor, StateRegulator, PlatformAdmin |
| GET | `/conversion-projects/{id}/escrow-summary` | Computed read of the project's escrow and relocation cash conservation snapshot. | ConverterSponsor, EscrowAgent, StateRegulator, PlatformAdmin |
| GET | `/conversion-projects/{id}/warrantability-summary` | Computed read of both contract-basis and closed-basis warrantability metrics. | ConverterSponsor, LenderUnderwriter, StateRegulator, PlatformAdmin |
| GET | `/conversion-projects/{id}/relocation-summary` | Computed read of the project's tenant relocation obligation ledger. | ConverterSponsor, StateRegulator, PlatformAdmin |
| POST | `/conversion-projects/{id}/engineering-reports` | Creates a draft engineering report for the project. | LicensedEngineer, ConverterSponsor |
| GET | `/conversion-projects/{id}/engineering-reports` | Lists a project's engineering reports, optionally filtered by status. | ConverterSponsor, LicensedEngineer, PeerReviewEngineer, StateRegulator, PlatformAdmin |
| GET | `/engineering-reports/{id}` | Returns one engineering report with its review progress counters. | ConverterSponsor, LicensedEngineer, PeerReviewEngineer, StateRegulator, PlatformAdmin |
| POST | `/engineering-reports/{id}/submit` | Submits a drafted engineering report for independent peer review. | LicensedEngineer |
| POST | `/engineering-reports/{id}/peer-review-decisions` | Records the peer reviewer's acceptance or rejection of a submitted report. | PeerReviewEngineer |
| POST | `/engineering-reports/{id}/revisions` | Reopens a rejected engineering report for revision. | LicensedEngineer |
| POST | `/engineering-reports/{id}/major-components` | Adds a major building component to a drafted engineering report. | LicensedEngineer |
| GET | `/engineering-reports/{id}/major-components` | Lists a report's major components with optional attribute filters. | LicensedEngineer, PeerReviewEngineer, ConverterSponsor, StateRegulator, PlatformAdmin |
| GET | `/major-components/{id}` | Returns one major component with its engineering and verification data. | LicensedEngineer, PeerReviewEngineer, ConverterSponsor, StateRegulator, PlatformAdmin |
| PATCH | `/major-components/{id}` | Adjusts a major component's engineering inputs. | LicensedEngineer |
| POST | `/major-components/{id}/verification` | Sets or clears a major component's independent verification. | PeerReviewEngineer |
| POST | `/engineering-reports/{id}/suitability-assessments` | Scores building suitability under the requested variant over verified components. | PeerReviewEngineer, ConverterSponsor |
| GET | `/engineering-reports/{id}/suitability-assessments` | Lists a report's suitability assessments with optional filters. | ConverterSponsor, PeerReviewEngineer, LicensedEngineer, StateRegulator, PlatformAdmin |
| GET | `/suitability-assessments` | Lists suitability assessments across a project so variants can be compared. | ConverterSponsor, PeerReviewEngineer, StateRegulator, LenderUnderwriter, PlatformAdmin |
| GET | `/suitability-assessments/{id}` | Returns one suitability assessment with its score, basis and verdict. | ConverterSponsor, PeerReviewEngineer, LicensedEngineer, StateRegulator, LenderUnderwriter, PlatformAdmin |
| POST | `/conversion-projects/{id}/declaration-packages` | Creates the project's draft declaration, bylaws and plat package. | ConverterSponsor |
| GET | `/conversion-projects/{id}/declaration-packages` | Lists a project's declaration packages, optionally filtered by status. | ConverterSponsor, StateRegulator, LenderUnderwriter, PlatformAdmin |
| GET | `/declaration-packages/{id}` | Returns one declaration package with its recording state and allocation total. | ConverterSponsor, StateRegulator, LenderUnderwriter, PlatformAdmin |
| PATCH | `/declaration-packages/{id}` | Updates a draft declaration package's document references and boundary convention. | ConverterSponsor |
| POST | `/declaration-packages/{id}/plat-certification` | Certifies the plat and unit boundaries once the interest allocation balances. | ConverterSponsor, LicensedEngineer |
| POST | `/declaration-packages/{id}/record` | Records the certified declaration with the registry. | ConverterSponsor, StateRegulator |
| POST | `/declaration-packages/{id}/units` | Defines a unit within the declaration package. | ConverterSponsor, LicensedEngineer |
| GET | `/declaration-packages/{id}/units` | Lists a declaration package's units with optional status filters. | ConverterSponsor, StateRegulator, LenderUnderwriter, LicensedEngineer, PlatformAdmin |
| GET | `/units` | Lists units across a project or declaration package with optional status filters. | ConverterSponsor, StateRegulator, LenderUnderwriter, EscrowAgent, PlatformAdmin, Purchaser, TenantOccupant |
| GET | `/units/{id}` | Returns one unit with its interest allocation and assessment figures. | ConverterSponsor, StateRegulator, LenderUnderwriter, EscrowAgent, PlatformAdmin, Purchaser, TenantOccupant |
| PATCH | `/units/{id}` | Adjusts an unsold unit's boundary and economic base inputs. | ConverterSponsor, LicensedEngineer |
| POST | `/units/{id}/withdraw` | Withdraws an included unit from the conversion. | ConverterSponsor |
| POST | `/units/{id}/reinstate` | Reinstates a previously withdrawn unit. | ConverterSponsor |
| GET | `/declaration-packages/{id}/assessment-allocation` | Computed read of per-unit interest and assessment allocation for the included units. | ConverterSponsor, StateRegulator, LenderUnderwriter, PlatformAdmin |
| POST | `/conversion-projects/{id}/public-offering-statements` | Creates the project's draft public offering statement. | ConverterSponsor |
| GET | `/conversion-projects/{id}/public-offering-statements` | Lists a project's public offering statements, optionally filtered by status. | ConverterSponsor, StateRegulator, LenderUnderwriter, Purchaser, PlatformAdmin |
| GET | `/public-offering-statements` | Lists public offering statements by their linked declaration, study or budget. | ConverterSponsor, StateRegulator, LenderUnderwriter, Purchaser, PlatformAdmin |
| GET | `/public-offering-statements/{id}` | Returns one public offering statement with its registration and amendment state. | ConverterSponsor, StateRegulator, LenderUnderwriter, Purchaser, PlatformAdmin |
| GET | `/public-offering-statements/{id}/sections` | Lists a statement's statutory sections with optional filters. | ConverterSponsor, StateRegulator, LenderUnderwriter, Purchaser, PlatformAdmin |
| GET | `/public-offering-statements/{id}/sections/{section_code}` | Returns one statutory section of a statement by its code. | ConverterSponsor, StateRegulator, LenderUnderwriter, Purchaser, PlatformAdmin |
| PUT | `/public-offering-statements/{id}/sections/{section_code}` | Writes the content of one statutory section of the statement. | ConverterSponsor |
| POST | `/public-offering-statements/{id}/effectiveness` | Registers the public offering statement as effective for sales. | StateRegulator |
| POST | `/public-offering-statements/{id}/amendments` | Files an amendment against an effective public offering statement. | ConverterSponsor |
| POST | `/conversion-projects/{id}/tenant-households` | Registers an existing tenant household of the building. | ConverterSponsor |
| GET | `/conversion-projects/{id}/tenant-households` | Lists a project's tenant households with optional status filters. | ConverterSponsor, StateRegulator, PlatformAdmin |
| GET | `/tenant-households` | Lists tenant households by occupied unit or project. | ConverterSponsor, StateRegulator, PlatformAdmin, TenantOccupant |
| GET | `/tenant-households/{id}` | Returns one tenant household with its notice, refusal and relocation state. | ConverterSponsor, StateRegulator, PlatformAdmin, TenantOccupant |
| PATCH | `/tenant-households/{id}` | Adjusts a household's pre-notice tenancy facts. | ConverterSponsor |
| POST | `/tenant-households/{id}/notices` | Serves the statutory conversion notice on the household. | ConverterSponsor |
| POST | `/tenant-households/{id}/rofr-responses` | Records the household's answer to its right of first refusal offer. | TenantOccupant, ConverterSponsor |
| POST | `/tenant-households/{id}/relocation-disbursements` | Pays the household's statutory relocation assistance. | EscrowAgent |
| POST | `/tenant-households/{id}/occupancy-outcomes` | Records how the tenancy ended after the vacate deadline. | ConverterSponsor |
| POST | `/conversion-projects/{id}/reserve-studies` | Produces a reserve study for the project under the requested funding method. | ConverterSponsor, LicensedEngineer |
| GET | `/conversion-projects/{id}/reserve-studies` | Lists a project's reserve studies with optional filters. | ConverterSponsor, StateRegulator, LenderUnderwriter, LicensedEngineer, PlatformAdmin |
| GET | `/reserve-studies` | Lists reserve studies so funding methods can be compared for one report. | ConverterSponsor, StateRegulator, LenderUnderwriter, LicensedEngineer, PlatformAdmin |
| GET | `/reserve-studies/{id}` | Returns one reserve study with its funding and adoption state. | ConverterSponsor, StateRegulator, LenderUnderwriter, LicensedEngineer, PlatformAdmin |
| PATCH | `/reserve-studies/{id}` | Adjusts a proposed reserve study's opening balance. | ConverterSponsor |
| POST | `/conversion-projects/{id}/initial-budgets` | Creates the project's first-year operating budget and its deficit disclosure. | ConverterSponsor |
| GET | `/conversion-projects/{id}/initial-budgets` | Lists a project's initial budgets with optional filters. | ConverterSponsor, StateRegulator, LenderUnderwriter, Purchaser, PlatformAdmin |
| GET | `/initial-budgets` | Lists initial budgets by their reserve study or project. | ConverterSponsor, StateRegulator, LenderUnderwriter, Purchaser, PlatformAdmin |
| GET | `/initial-budgets/{id}` | Returns one initial budget with its derived expense, income and deficit figures. | ConverterSponsor, StateRegulator, LenderUnderwriter, Purchaser, PlatformAdmin |
| PATCH | `/initial-budgets/{id}` | Adjusts a draft budget's annual operating expense. | ConverterSponsor |
| POST | `/initial-budgets/{id}/adoption` | Adopts the draft budget as the project's governing first-year budget. | ConverterSponsor, StateRegulator |
| POST | `/conversion-projects/{id}/closing-batches` | Creates a closing batch that holds closings over a non-overlapping window. | ConverterSponsor |
| GET | `/conversion-projects/{id}/closing-batches` | Lists a project's closing batches, optionally filtered by status. | ConverterSponsor, EscrowAgent, StateRegulator, LenderUnderwriter, PlatformAdmin |
| GET | `/closing-batches/{id}` | Returns one closing batch with its window, thresholds and counters. | ConverterSponsor, EscrowAgent, StateRegulator, LenderUnderwriter, PlatformAdmin |
| PATCH | `/closing-batches/{id}` | Adjusts a pre-release batch's window and minimum thresholds. | ConverterSponsor |
| POST | `/closing-batches/{id}/agreement-assignments` | Assigns an unassigned purchase agreement to the batch. | ConverterSponsor, EscrowAgent |
| GET | `/closing-batches/{id}/agreements` | Lists the purchase agreements assigned to a batch. | ConverterSponsor, EscrowAgent, StateRegulator, LenderUnderwriter, PlatformAdmin |
| DELETE | `/closing-batches/{id}/agreement-assignments/{purchase_agreement_id}` | Unassigns an agreement from a batch that has not been released. | ConverterSponsor |
| POST | `/closing-batches/{id}/threshold-evaluations` | Evaluates the batch against both minimum presale thresholds. | ConverterSponsor, EscrowAgent, StateRegulator |
| POST | `/closing-batches/{id}/release` | Releases a qualifying batch so its agreements may close. | EscrowAgent |
| GET | `/closing-batches/{id}/threshold-summary` | Computed read of a batch's presale metrics without changing its status. | ConverterSponsor, EscrowAgent, StateRegulator, LenderUnderwriter, PlatformAdmin |
| POST | `/units/{id}/purchase-agreements` | Signs a purchase agreement on an included unit. | ConverterSponsor, Purchaser |
| GET | `/units/{id}/purchase-agreements` | Lists the purchase agreements on a unit with optional status filters. | ConverterSponsor, EscrowAgent, StateRegulator, LenderUnderwriter, Purchaser, PlatformAdmin |
| GET | `/purchase-agreements` | Lists purchase agreements by project, statement, batch or household. | ConverterSponsor, EscrowAgent, StateRegulator, LenderUnderwriter, Purchaser, PlatformAdmin |
| GET | `/purchase-agreements/{id}` | Returns one purchase agreement with its pricing, deadlines and state dimensions. | ConverterSponsor, EscrowAgent, StateRegulator, LenderUnderwriter, Purchaser, PlatformAdmin |
| PATCH | `/purchase-agreements/{id}` | Adjusts an unhardened agreement's purchaser and pricing details. | ConverterSponsor |
| POST | `/purchase-agreements/{id}/pos-deliveries` | Records delivery of the effective statement and opens the rescission period. | ConverterSponsor |
| POST | `/purchase-agreements/{id}/escrow-deposits` | Funds the agreement's earnest money deposit into escrow. | EscrowAgent |
| POST | `/purchase-agreements/{id}/hardening` | Hardens the contract once the rescission period has closed. | ConverterSponsor, EscrowAgent |
| POST | `/purchase-agreements/{id}/rescission` | Exercises the purchaser's statutory rescission right. | Purchaser, ConverterSponsor |
| POST | `/purchase-agreements/{id}/closing` | Closes the sale for an agreement held in a released batch. | EscrowAgent |
| POST | `/conversion-projects/{id}/warranty-claims` | Files a common-element warranty claim against a major component. | ConverterSponsor, Purchaser |
| GET | `/conversion-projects/{id}/warranty-claims` | Lists a project's warranty claims with optional filters. | ConverterSponsor, StateRegulator, LenderUnderwriter, Purchaser, PlatformAdmin |
| GET | `/warranty-claims` | Lists warranty claims by component, reporting unit or project. | ConverterSponsor, StateRegulator, LenderUnderwriter, Purchaser, LicensedEngineer, PlatformAdmin |
| GET | `/warranty-claims/{id}` | Returns one warranty claim with its triage, charge and window data. | ConverterSponsor, StateRegulator, LenderUnderwriter, Purchaser, LicensedEngineer, PlatformAdmin |
| POST | `/warranty-claims/{id}/triage` | Records the admissibility decision on a submitted or reopened claim. | LicensedEngineer, ConverterSponsor |
| POST | `/warranty-claims/{id}/remediation-schedule` | Schedules the remediation window for an admissible claim. | ConverterSponsor |
| POST | `/warranty-claims/{id}/completion` | Records completion of a scheduled remediation. | ConverterSponsor, LicensedEngineer |
| POST | `/warranty-claims/{id}/reopening` | Reopens a remediated claim whose defect recurred. | ConverterSponsor, Purchaser |
| GET | `/conversion-projects/{id}/warranty-summary` | Computed read of warranty charge accrual and remediation overlap depth. | ConverterSponsor, StateRegulator, LenderUnderwriter, PlatformAdmin |

## 5. Error Code Catalogue

Every error response carries its identifier as the `error_id` inside the envelope's `data` object, exactly as described in §2.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_AUTH_HEADERS` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_IDENTITY_MISMATCH` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_ENGINEERING_ARTIFACT_NOT_FOUND` | 404 |
| `ERR_DECLARATION_ARTIFACT_NOT_FOUND` | 404 |
| `ERR_DISCLOSURE_ARTIFACT_NOT_FOUND` | 404 |
| `ERR_TENANT_NOT_FOUND` | 404 |
| `ERR_FINANCIAL_ARTIFACT_NOT_FOUND` | 404 |
| `ERR_SALES_ARTIFACT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_PAGINATION` | 422 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_STALE_UNIT_VERSION` | 412 |
| `ERR_STALE_REPORT_VERSION` | 412 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_STALE_BATCH_VERSION` | 412 |
| `ERR_PROJECT_FROZEN` | 409 |
| `ERR_PROJECT_RESTRICTED` | 409 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_BATCH_NOT_RELEASED` | 409 |
| `ERR_POS_NOT_EFFECTIVE` | 409 |
| `ERR_DECLARATION_NOT_RECORDED` | 409 |
| `ERR_RESERVE_STUDY_NOT_ADOPTED` | 409 |
| `ERR_POS_NOT_DELIVERED` | 409 |
| `ERR_LIFE_SAFETY_COMPONENT_EXPIRED` | 422 |
| `ERR_SUITABILITY_GATE_FAILED` | 409 |
| `ERR_NO_VERIFIED_COMPONENTS` | 409 |
| `ERR_POS_SECTIONS_INCOMPLETE` | 409 |
| `ERR_NOTICE_PERIOD_NOT_ELAPSED` | 409 |
| `ERR_ROFR_WINDOW_EXPIRED` | 409 |
| `ERR_RESCISSION_PERIOD_OPEN` | 409 |
| `ERR_RESCISSION_PERIOD_CLOSED` | 409 |
| `ERR_WARRANTY_PERIOD_EXPIRED` | 409 |
| `ERR_BATCH_WINDOW_OVERLAP` | 409 |
| `ERR_REMEDIATION_WINDOW_OVERLAP` | 409 |
| `ERR_REMEDIATION_CAPACITY_EXCEEDED` | 409 |
| `ERR_PROJECT_SCOPE_MISMATCH` | 409 |
| `ERR_ROFR_UNIT_NOT_LINKED` | 409 |
| `ERR_AGREEMENT_ALREADY_ASSIGNED` | 409 |
| `ERR_PERCENTAGE_INTEREST_NOT_BALANCED` | 409 |
| `ERR_LAST_INCLUDED_UNIT` | 409 |
| `ERR_NO_INCLUDED_UNITS` | 409 |
| `ERR_CLAIM_REOPEN_LIMIT_REACHED` | 409 |
| `ERR_ESCROW_AMOUNT_MISMATCH` | 422 |
| `ERR_ESCROW_NOT_FUNDED` | 402 |
| `ERR_RELOCATION_AMOUNT_MISMATCH` | 422 |
| `ERR_PRESALE_THRESHOLD_NOT_MET` | 409 |
