# Genealogy Research API — Product Requirements Document

## 1. Introduction

Professional genealogy is a long, evidence-driven engagement: a paying client commissions a research request, a genealogist searches archives and repositories, cites the sources that support each ancestor placed on a family tree, and — over weeks or months — assembles verified findings into deliverable reports and trees that are billed against agreed milestones. The work is messy in ways that ordinary project software handles poorly. Evidence arrives out of order and is sometimes later disputed, so a person who was "verified" last month may need to be reopened. Hours accrue against a budget that can legitimately overrun, but only up to a hard cap. Physical archive visits compete for scarce seats and for a researcher's exclusive attention. And money moves through a milestone ledger where an invoice can later be reversed by a compensating credit without pretending it was never issued.

This document specifies a backend API that models that full workflow as a set of interlocking resources: clients, researchers, and repositories as the acting parties and physical archives; research projects as the engagement contract; record searches, source citations, and persons as the research substrate; DNA interpretations, document retrieval/translation requests, and heirloom items as specialized add-ons; and deliverables, milestones, and time entries as the delivery-and-billing layer. The service is written for three cooperating operators — the client who commissions and accepts work, the genealogist who performs it, and the project manager who provisions actors and runs billing — and its central design goal is that every derived number (a project's cost, a person's confidence, a milestone's invoiced total, a project's outstanding balance) is reconciled immediately and deterministically from the underlying events, so that any reader of the API sees a consistent picture at every step.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the request is made. If either header is missing, or if `X-User-Role` is not one of the three recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The three roles are `Client`, `Researcher`, and `ProjectManager`.

When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client` entity; ownership checks on any resource that references a client compare the resource's owning client to `X-User-ID`. Concretely, a `Client` may accept or request revision on a deliverable only when the deliverable's owning project names that same client, i.e. the project's `client_id` equals `X-User-ID`; otherwise the request is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403).

When `X-User-Role` is `Researcher`, `X-User-ID` is the `id` of the acting `Researcher` entity. The server records this identifier on artifacts the researcher produces — it becomes the `performed_by_id` on a record search and the `researcher_id` on a time entry — rather than trusting a client-supplied value for those two fields.

When `X-User-Role` is `ProjectManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; a project manager acts as a system operator who provisions actors and repositories, runs the project and milestone lifecycles, and drives the logical clock.

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

All list endpoints accept two pagination parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be at least 0. Results are ordered by `created_at` ascending (oldest first); where two resources share a creation instant, insertion order breaks the tie. Each list response reports `limit`, `offset`, `total_count` (the number of records matching the filter before the page window is applied), and `has_more` (true when records remain beyond the current window) inside the `meta` object.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries four common properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation, and `updated_at` advances on every mutation that changes the resource. `version` is an integer that begins at 1 when the resource is created and increments by exactly 1 on each mutation. Whenever a state transition or field update is applied to a resource, its `version` is incremented and its `updated_at` refreshed as part of the same operation. Where an operation cascades into a second resource (for example, verifying a person that in turn touches its project), the secondary resource's `version` and `updated_at` advance as well.

Creating a new resource returns HTTP 201; every other successful mutation, including all state transitions, returns HTTP 200. Reads return HTTP 200.

### 2.5. Reference Resolution and Validation Ordering

Requests are validated in a fixed precedence so that failures are reported deterministically. Authentication (`ERR_UNAUTHENTICATED`) is evaluated first, then authorization by role (`ERR_UNAUTHORIZED`). Next, the existence of every referenced resource is checked left to right — path identifiers first, then foreign-key references carried in the body — and the first missing reference yields the corresponding not-found error (for example, an unknown project yields `ERR_PROJECT_NOT_FOUND`, an unknown person yields `ERR_PERSON_NOT_FOUND`, and so on for each entity, all HTTP 404). Malformed payloads — a missing required field, a value of the wrong type, or an enum value outside its permitted set — are rejected with `ERR_VALIDATION` (HTTP 400). Ownership checks (`ERR_FORBIDDEN_NOT_OWNER`) follow existence. Only once a request is authenticated, authorized, well-formed, and its references resolved does the server evaluate state-machine and business rules described throughout §3.

Where several business rules guard the same operation, their relative order is specified alongside the workflow that they protect (see §3). In all cases, a state-admissibility failure (the resource is not in a state that admits the requested transition) surfaces as `ERR_INVALID_STATE` (HTTP 409).

### 2.6. Optimistic Concurrency on Project Reconfiguration

A research project's commercial terms — its package, budget, price, and priority — may be revised while the project is still a draft, but only under optimistic concurrency control. A reconfigure request must carry `expected_project_version`, the `version` of the project the client last observed. The server compares this value against the project's current `version`: if another writer has advanced the project's `version` since the client last read it, the reconfigure is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), because a reconfigure legitimately supersedes the prior package terms and a now-stale request must not silently overwrite the newer ones. Only when `expected_project_version` matches the current `version` is the update applied (and the `version` then incremented). No other endpoint accepts or requires a version field; reconfigure is the sole optimistic-concurrency-guarded operation.

### 2.7. Monetary and Confidence Precision

All money is represented in integer cents; there are no fractional cents. Wherever a monetary computation produces a non-integer intermediate — a percentage discount, a percentage agency fee, a price cap — the result is rounded half up to the nearest whole cent, and the order in which rounding is applied relative to other operations is pinned by the calculation that uses it (see §3.9). Confidence scores are decimal fractions carried to two decimal places, also rounded half up, and clamped so that they never exceed 1.00. Overage-hour costs round the number of overage hours up to the next whole hour before multiplying by the per-hour rate.

### 2.8. Repository Scheduling Invariants

Physical archive visits are modeled as booked appointments that consume two distinct scarce resources: a researcher's undivided attention, and a repository's limited number of simultaneous seats. Two invariants therefore govern booking, and both are described with the appointment workflow in §3.6. The logical clock the server uses to compare appointment intervals is an operator-controlled, test-driving value: at startup it reads exactly `2026-03-01T00:00:00Z`, and until an operator sets it, it holds that instant and never falls back to wall-clock time.

## 3. Business Logic & Workflows

### 3.1. Provisioning Actors and Opening a Research Request

Before any research can begin, a project manager provisions the parties. Registering a `Client` supplies the client's `name` and contact `email`, which must be unique across all clients, and optionally a billing `tier`; when omitted, `tier` defaults to `STANDARD`, the only other permitted value being `PREMIUM`. A client also carries a lifecycle `status` that begins at `ACTIVE` and may otherwise be `ARCHIVED`. Registering a `Researcher` supplies a `name`, a unique `email`, an `hourly_rate_cents` labor rate that must be zero or greater (used only for informational costing), and an optional array of free-text `specialties` tags that defaults to empty. Registering a `Repository` supplies a `name`, a physical `location`, and an optional `concurrent_capacity` — the maximum number of BOOKED appointments whose time windows may overlap at that repository — which must be at least 1 and defaults to 2.

A research request is opened as a `ResearchProject`. Either the client themselves or a project manager may open one. The request names the paying `client_id`, the `lead_researcher_id` who will lead the work, a `title`, a research `objective`, and an optional `scope_note` describing scope boundaries (defaulting to an empty string). It also fixes the commercial terms: a `package_type` of `HOURLY`, `BASIC_PACKAGE`, or `PREMIUM_PACKAGE`; a `package_price_cents` fixed price of zero or more that forms the base of project cost; a `budget_hours` allotment of included research hours, which must be greater than zero; an optional scheduling `priority` of `STANDARD` (the default) or `RUSH`, where `RUSH` later adds a per-milestone invoice surcharge; and an optional `target_person_count`, the number of verified persons that marks research complete, which must be at least 1 and defaults to 1. A newly opened project begins in `status` `DRAFT`.

### 3.2. The Project Lifecycle and the Hours Ledger

A project moves through three lifecycle states — `DRAFT`, `ACTIVE`, and the terminal `CLOSED` — all driven by the project manager. Activating a project advances it `DRAFT → ACTIVE` and is permitted only when the project is currently `DRAFT`; attempting it from any other state fails with `ERR_INVALID_STATE`. Closing a project advances it `ACTIVE → CLOSED` and is permitted only from `ACTIVE`. While a project is still `DRAFT`, its commercial terms may be revised under the optimistic-concurrency rule of §2.6: a reconfigure is admissible only when the project is `DRAFT` (checked first, yielding `ERR_INVALID_STATE` from any other state) and then only when `expected_project_version` matches the current `version` (checked next, yielding `ERR_STALE_PROJECT_VERSION`); a successful reconfigure updates whichever of `package_type`, `budget_hours`, `package_price_cents`, and `priority` are supplied and leaves the others untouched.

Alongside its stored terms, a project exposes a family of derived figures that are reconciled from the underlying events. `consumed_hours` is the sum of the `hours` of every time entry belonging to the project that is both in status `ACTIVE` and marked billable. A project also tracks `verified_person_count` (the number of its persons currently `VERIFIED`), `accepted_deliverable_count` (the number of its deliverables that have reached `ACCEPTED`), and `ready_milestone_amount_cents` (the sum of the base `amount_cents` of its milestones currently in `READY`). The `research_status` is derived and holds `IN_PROGRESS` until `verified_person_count` reaches or exceeds `target_person_count`, at which point it flips to `RESEARCH_COMPLETE`; should a later reopening drop the verified count back below the target, it returns to `IN_PROGRESS`. This recomputation runs automatically whenever a person is verified or reopened and leaves the project in `ACTIVE`.

Hours are logged as `TimeEntry` records against an `ACTIVE` project by the assigned researcher. A time entry names its `project_id`, records the acting researcher as `researcher_id` from `X-User-ID`, optionally references the `record_search_id` whose work it covers (nullable), and carries the `hours` worked (which must be greater than zero), an `activity_type` of `RESEARCH`, `WRITING`, `TRANSLATION`, `ADMIN`, or `TRAVEL`, and a `billable` flag that defaults to true. A new entry begins in `status` `ACTIVE`. Logging time is admissible only when the owning project is `ACTIVE`; otherwise the attempt fails with `ERR_PROJECT_NOT_ACTIVE` (this project-active check is evaluated before the budget check). Billable hours are further capped: when the entry is billable, the project's current `consumed_hours` plus the new entry's billable `hours` must not exceed 1.5 times `budget_hours`; a log that would push the running billable total past that hard cap is rejected with `ERR_HOURS_CAP_EXCEEDED`. Creating a billable entry adds its `hours` to `consumed_hours` and refreshes the project's actual cost. An entry may later be voided (`ACTIVE → VOIDED`), which is a compensating action: if the entry was billable, its `hours` are subtracted back out of `consumed_hours`, and the project's actual cost is recomputed, so that consumed hours are conserved across a create-then-void pair.

A project's cost is reported through two parallel variants, both denominated in integer cents on the fixed base of `package_price_cents`, and both recomputed when the project is read as well as when the underlying searches or time entries change. The overage rate is 80 US dollars — 8000 cents — per whole overage hour. The **estimated** variant, `estimated_cost_cents`, is forward-looking: it sums the `estimated_hours` of every record search on the project that has not been cancelled (those in `PENDING`, `COMPLETED`, or `NO_RESULTS`), subtracts `budget_hours` to obtain the projected overage, treats any negative result as zero overage, rounds that overage figure up to the next whole hour, multiplies by 8000 cents, and adds the product to `package_price_cents`. The **actual** variant, `actual_cost_cents`, accounts logged work instead: it sums the `hours` of the project's `ACTIVE` billable time entries in chronological order of creation, subtracts `budget_hours`, floors the overage at zero, rounds it up to the next whole hour, multiplies by 8000 cents, and adds the product to `package_price_cents`. The two variants differ only in their inclusion set — planned searches versus logged hours — and never borrow from one another.

### 3.3. Record Searches

Research proceeds through `RecordSearch` records logged by a researcher (or a project manager) against an `ACTIVE` project; a search created against a project that is not `ACTIVE` is rejected with `ERR_PROJECT_NOT_ACTIVE`. A search names its `project_id`, the free-text `repository_name` that was searched, the `search_terms` used, and an `estimated_hours` figure of zero or more that feeds the estimated cost variant above; the acting researcher is stamped as `performed_by_id` from `X-User-ID`. It begins in `status` `PENDING` and carries a `result_summary` that defaults to an empty string. Completing a search is a researcher action that supplies an `outcome`: an `outcome` of `COMPLETED` advances the search `PENDING → COMPLETED` and stores the supplied `result_summary`, while an `outcome` of `NO_RESULTS` advances it `PENDING → NO_RESULTS`. Either transition is admissible only from `PENDING`. The status enumeration also includes `CANCELLED` for searches abandoned before completion. Creating a search refreshes the project's estimated cost.

### 3.4. Building and Verifying the Family Tree

The family tree is a graph of `Person` nodes created by the researcher. Each person names its owning `project_id` and a `full_name`, and optionally a `birth_year` and `death_year` (both nullable). Genealogical descent is expressed by two self-referential parent links, `father_id` and `mother_id`, each a nullable reference to another person; the list endpoint for persons can be filtered by either link to walk the tree. A new person begins with `verification_status` `DRAFT`. Each person also exposes four derived figures: `citation_count`, the number of its non-disputed citations; `verified_citation_count`, the number of its `VERIFIED` citations; `provisional_confidence`, a display figure computed from all non-disputed evidence; and `confidence_score`, the authoritative figure computed from verified evidence alone, which gates verification.

Evidence is attached as `SourceCitation` records, created by a researcher. A citation supplies the `record_search_id` that produced it, the `person_id` it supports, the formatted `citation_text`, a `source_type` of `VITAL_RECORD`, `CENSUS`, `CHURCH`, `DNA`, or `OTHER`, and a `quality` of `PRIMARY`, `SECONDARY`, or `INDIRECT`. The server copies the `project_id` onto the citation from the referenced record search rather than trusting the caller. Two guards protect citation creation and are evaluated in this order after the referenced search and person are confirmed to exist: the search and the person must belong to the same project, or the request fails with `ERR_CROSS_PROJECT_REFERENCE`; and the referenced record search must be in `COMPLETED`, since a search that has not produced results cannot be cited, or the request fails with `ERR_SEARCH_NOT_COMPLETED`. A new citation begins with `verification_status` `UNVERIFIED` and, on creation, recomputes the owning person's `citation_count` and `provisional_confidence`.

A person's confidence is a weighted score. Each supporting citation contributes points by quality — a `PRIMARY` citation is worth 3 points, a `SECONDARY` citation 2 points, and an `INDIRECT` citation 1 point — and the point total is divided by 6, capped at 1.00, and rounded half up to two decimal places. The provisional figure, `provisional_confidence`, sums the points of every citation for the person that is not `DISPUTED` (that is, `UNVERIFIED` and `VERIFIED` citations alike). The authoritative figure, `confidence_score`, sums the points of only the person's `VERIFIED` citations. Both figures are recomputed on every citation event affecting the person.

A citation's own verification is a small state machine. Verifying a citation advances it `UNVERIFIED → VERIFIED`; it must currently be `UNVERIFIED`. Disputing a citation advances it to `DISPUTED` from either `UNVERIFIED` or `VERIFIED` and accepts an optional `reason`; it may not be disputed once already disputed. Every verify or dispute recomputes the affected person's `confidence_score` and `verified_citation_count` (and, on a dispute, its `citation_count` as well), and these recomputations may cascade into the person's own verification state as described next.

A person advances through `DRAFT`, `UNDER_REVIEW`, and `VERIFIED`. Submitting a person for review advances it `DRAFT → UNDER_REVIEW` and is admissible only from `DRAFT`. A person may reach `VERIFIED` two ways, both gated identically. When a researcher (or project manager) explicitly verifies a person, the person must currently be `UNDER_REVIEW` (else `ERR_INVALID_STATE`), must have at least 2 `VERIFIED` citations (else `ERR_INSUFFICIENT_CITATIONS`), and must have a `confidence_score` of at least 0.75 (else `ERR_CONFIDENCE_BELOW_THRESHOLD`); these three checks are evaluated in that order — state admissibility first, then the citation-count floor, then the confidence floor. Alternatively, the person is auto-verified as a side effect of citation verification: when verifying a citation leaves its person `UNDER_REVIEW` with a `confidence_score` of at least 0.75 and a `verified_citation_count` of at least 2, the person is driven `UNDER_REVIEW → VERIFIED` automatically. Either path to `VERIFIED` increments the owning project's `verified_person_count` by 1 and then recomputes the project's `research_status`.

Verification is reversible, which is what makes the person node cyclic. When a dispute drops a currently `VERIFIED` person below either gate — its `confidence_score` falls under 0.75, or its `verified_citation_count` falls under 2 — the system reopens the person `VERIFIED → UNDER_REVIEW`, decrements the owning project's `verified_person_count` by 1, and recomputes the project's `research_status`. This reopen is driven automatically by the disputing citation event rather than by any direct call.

### 3.5. DNA Interpretation Add-On

A `DnaInterpretation` is an add-on ordered by a researcher against a project. Ordering one names the `project_id`, the `subject_person_id` of the tested individual, the `test_provider` vendor, an optional `match_person_id` naming a matched relative (nullable), and an optional `addon_fee_cents` service fee of zero or more that defaults to 15000 cents. A new interpretation begins in `status` `ORDERED` with a null `predicted_relationship` and no `cm_shared` yet recorded. Interpreting the result advances it `ORDERED → INTERPRETED` and supplies the `cm_shared` shared-centimorgan measurement (zero or greater). Interpretation is admissible only when the interpretation is `ORDERED` and the subject person is `VERIFIED`; if the subject is not verified the request fails with `ERR_SUBJECT_NOT_VERIFIED`. The `predicted_relationship` is then derived from `cm_shared` by inclusive lower-bound bands: 3400 centimorgans or more predicts `PARENT_CHILD`; from 2000 up to (but not reaching) 3400 predicts `FULL_SIBLING`; from 1300 up to 2000 predicts `CLOSE_FAMILY`; from 200 up to 1300 predicts `COUSIN`; and anything below 200 predicts `UNRELATED`. An interpretation may also reach the terminal `CANCELLED` state under project-manager or system control when the owning project is closed while the interpretation is still `ORDERED`.

### 3.6. Document Retrieval, Translation, and Repository Visits

A `DocumentRequest` tracks the sourcing of an archival document along two independent dimensions. Creating one, a researcher names the `project_id`, the `repository_id` where the document lives, the `document_type`, the `source_language` of the original, an optional `pages` count that must be at least 1 and defaults to 1, and an optional `needs_translation` flag. Retrieval and translation progress separately. The `retrieval_status` begins at `REQUESTED` and may advance to `RETRIEVED` or `UNAVAILABLE`. The `translation_status` begins at `PENDING` when the request was created with `needs_translation` set to true, and otherwise at `NOT_NEEDED`; from `PENDING` it may advance to `TRANSLATED`. Advancing retrieval is a researcher action that supplies an `outcome` of `RETRIEVED` or `UNAVAILABLE` and is admissible only while `retrieval_status` is `REQUESTED`. Advancing translation supplies an `outcome` of `TRANSLATED` and is admissible only while `translation_status` is `PENDING`. Because the two dimensions are independent, advancing one never affects the other; each advance simply increments the request's `version`.

Archive visits are booked as `RepositoryAppointment` records by a researcher. A booking names the `repository_id` being visited, the owning `project_id`, the attending `researcher_id`, a `start_utc` and `end_utc` in ISO 8601 UTC, and an optional visit `purpose` (defaulting to an empty string). A new appointment begins in `status` `BOOKED`. Three rules guard booking, evaluated in this order once the referenced repository, project, and researcher are known to exist. First, the visit must not collide with the same researcher's undivided attention: a new booking may not fall within 30 minutes — the researcher buffer — of another `BOOKED` appointment for that researcher, so a proposed window whose start-to-end interval, padded by that buffer, touches an existing booked interval for the researcher is rejected with `ERR_RESEARCHER_UNAVAILABLE`. Second, the repository's seats must not be oversubscribed: a booking that would push the count of time-overlapping `BOOKED` appointments at that repository above the repository's `concurrent_capacity` is rejected with `ERR_REPOSITORY_AT_CAPACITY`. Third, the interval itself must be well-formed: `end_utc` must be strictly after `start_utc`, or the request is rejected with `ERR_INVALID_INTERVAL`. A booked appointment may later be cancelled (`BOOKED → CANCELLED`), which frees the researcher's and repository's interval so the seat and the researcher's time become available again; the enumeration also includes a `COMPLETED` terminal state for visits that have taken place. All interval comparisons are made against the server's logical clock, which an operator may advance to a supplied `to_iso8601` instant through an administrative test-driving capability.

### 3.7. The Heirloom Archive Pipeline

Family heirlooms and archival items are tracked as `HeirloomItem` records, accessioned by a researcher or project manager. Each names its `project_id`, a `description`, and a `category` of `PHOTO`, `DOCUMENT`, `ARTIFACT`, `TEXTILE`, or `OTHER`, and optionally a `related_person_id` linking it to a person on the tree (nullable) and a `storage_location` (defaulting to an empty string). An item moves through a strictly linear archival pipeline reflected in its `archive_status`: it begins at `RECEIVED` and is advanced one step at a time by supplying the next `target_status` — from `RECEIVED` to `CATALOGUED`, then to `DIGITIZED`, and finally to the terminal `RETURNED`. Each advance is admissible only from the immediately preceding state, so skipping a step or moving backward fails with `ERR_INVALID_STATE`.

### 3.8. Deliverables and the Revision Cycle

Findings are packaged as `Deliverable` records created by a researcher. A deliverable names its `project_id`, a `deliverable_type` of `RESEARCH_REPORT`, `FAMILY_TREE`, or `DNA_SUMMARY`, an optional `page_count` (at least 1, defaulting to 1), and an optional `milestone_id` naming the billing milestone whose readiness its acceptance will unlock (nullable). It begins in `status` `DRAFT` and runs a review cycle between the researcher and the client. Submitting a deliverable advances it to `SUBMITTED`, admissible either from `DRAFT` or, on a resubmission, from `REVISION_REQUESTED`. From `SUBMITTED`, the client decides: requesting a revision advances it `SUBMITTED → REVISION_REQUESTED` with optional `notes`, sending it back to the researcher for another pass, while accepting it advances it `SUBMITTED → ACCEPTED`, a terminal state. Both client decisions are admissible only from `SUBMITTED`, and both are restricted to the client who owns the deliverable's project (or a project manager); a client who does not own the project is refused with `ERR_FORBIDDEN_NOT_OWNER`.

Acceptance is the hinge between research and billing. Accepting a deliverable increments the owning project's `accepted_deliverable_count` by 1 and, when the deliverable names a `milestone_id`, drives that linked milestone from `PENDING` to `READY`; that milestone's move to `READY` in turn recomputes the project's `ready_milestone_amount_cents`. A deliverable with no linked milestone simply records its acceptance without touching the billing ledger.

### 3.9. Milestone Billing and Reconciliation

Billing is organized as `Milestone` records created by a project manager. A milestone names its `project_id`, a `title`, a base `amount_cents` of zero or more before any discount or surcharge, a `sequence_no` ordering index of at least 1, and optionally the `deliverable_id` whose acceptance readies it (nullable). It exposes two computed money fields, `invoiced_amount_cents` and `line_total_cents`, both stamped at invoice time and both zero until then, and it runs through the billing states `PENDING`, `READY`, `INVOICED`, `PAID`, and `CANCELLED`, of which `PAID` and `CANCELLED` are terminal. A milestone becomes `READY` only as the cascade from accepting its linked deliverable, described in §3.8; that transition recomputes the project's `ready_milestone_amount_cents`.

Invoicing advances a milestone `READY → INVOICED` and is the moment its charge is computed. The invoiced amount begins from the milestone's base `amount_cents`. A tier discount is applied first: a `STANDARD` client receives no discount, while a `PREMIUM` client receives 10 percent off, and the discounted figure is rounded half up to a whole cent *before* any surcharge is considered. Then a rush surcharge is added: if the owning project's `priority` is `RUSH`, a flat 5000 cents is added to the rounded, discounted amount; otherwise nothing is added. The resulting pre-cap figure is finally capped so it can never exceed 1.5 times the base `amount_cents` (that cap itself rounded half up): the milestone's `invoiced_amount_cents` is the smaller of the pre-cap figure and the rounded price cap. At the same moment, the milestone's `line_total_cents` is stamped as its `invoiced_amount_cents` plus a per-milestone agency fee of 7.5 percent of `invoiced_amount_cents`, that fee rounded half up to a whole cent. Invoicing then adds the milestone's `line_total_cents` to the project's `invoiced_total_cents` — a running accumulator that is never decremented — and recomputes the project's `outstanding_balance_cents` and `billable_amount_cents`.

The project's `billable_amount_cents` reconciles the ledger with the same pinned rounding discipline: it is formed by walking every milestone on the project whose status is `INVOICED` or `PAID`, in order of `sequence_no` ascending with creation time breaking ties, computing each milestone's agency fee as 7.5 percent of its `invoiced_amount_cents` rounded half up to a whole cent, adding that fee to the milestone's `invoiced_amount_cents` to form its `line_total_cents`, and summing those per-milestone line totals. The fee is rounded per milestone before summation — never by taking a percentage of the aggregate — so the total is the sum of the individually rounded line totals.

Recording a payment advances a milestone `INVOICED → PAID` and adds its `line_total_cents` to the project's `paid_total_cents`, then recomputes `outstanding_balance_cents`. Cancelling a milestone is a compensating action available from either `READY` or `INVOICED`. Cancelling a `READY` milestone (one not yet invoiced) simply recomputes the project's `ready_milestone_amount_cents`. Cancelling an `INVOICED` milestone, by contrast, does not undo the invoice: instead it adds the milestone's `line_total_cents` to the project's `credited_total_cents` as a compensating credit and recomputes `outstanding_balance_cents` and `billable_amount_cents`, so that `invoiced_total_cents` stays put while the credit offsets it. Cancellation accepts an optional `reason`. Throughout, the project's `outstanding_balance_cents` is defined as `invoiced_total_cents` less `paid_total_cents` less `credited_total_cents`, and the project separately reports its `paid_total_cents` as the running sum of the line totals of milestones that have reached `PAID`. The net effect is that invoicing a milestone raises the outstanding balance by its line total, paying it or crediting it each lowers the outstanding balance by that same amount, and a cancel-after-invoice returns net billed money and the outstanding balance to their pre-invoice values.

## 4. Endpoint Definitions

Resource creation returns HTTP 201; all other successful mutations, including every state transition, and all reads return HTTP 200. Request and response payloads are not repeated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /genealogy/clients | Provision a client | ProjectManager |
| GET | /genealogy/clients/{id} | Fetch a client | ProjectManager, Client |
| POST | /genealogy/researchers | Provision a researcher | ProjectManager |
| GET | /genealogy/researchers/{id} | Fetch a researcher | ProjectManager, Researcher |
| POST | /genealogy/repositories | Provision a repository/archive | ProjectManager |
| GET | /genealogy/repositories/{id} | Fetch a repository | ProjectManager, Researcher |
| POST | /genealogy/projects | Open a research request/project | Client, ProjectManager |
| GET | /genealogy/projects/{id} | Fetch a project with computed cost/billing/verification fields | Client, Researcher, ProjectManager |
| GET | /genealogy/projects | List projects, filterable | Client, Researcher, ProjectManager |
| POST | /genealogy/projects/{id}/activate | Activate a project | ProjectManager |
| POST | /genealogy/projects/{id}/close | Close a project | ProjectManager |
| POST | /genealogy/projects/{id}/reconfigure | Reconfigure package/budget/price/priority while draft | ProjectManager |
| POST | /genealogy/record-searches | Log a record search | Researcher, ProjectManager |
| GET | /genealogy/record-searches/{id} | Fetch a record search | Client, Researcher, ProjectManager |
| GET | /genealogy/record-searches | List record searches, filterable | Client, Researcher, ProjectManager |
| POST | /genealogy/record-searches/{id}/complete | Complete a search | Researcher |
| POST | /genealogy/citations | Attach a source citation from a completed search | Researcher |
| GET | /genealogy/citations/{id} | Fetch a citation | Client, Researcher, ProjectManager |
| GET | /genealogy/citations | List citations, filterable | Client, Researcher, ProjectManager |
| POST | /genealogy/citations/{id}/verify | Verify a citation; cascades to person | Researcher, ProjectManager |
| POST | /genealogy/citations/{id}/dispute | Dispute a citation; may reopen a person | Researcher, ProjectManager |
| POST | /genealogy/persons | Add a person node to the family tree | Researcher |
| GET | /genealogy/persons/{id} | Fetch a person with confidence fields | Client, Researcher, ProjectManager |
| GET | /genealogy/persons | List persons, filterable | Client, Researcher, ProjectManager |
| POST | /genealogy/persons/{id}/submit-review | Submit a person for verification | Researcher |
| POST | /genealogy/persons/{id}/verify | Verify a person; enforces citation/confidence gates | Researcher, ProjectManager |
| POST | /genealogy/dna-interpretations | Order a DNA interpretation add-on | Researcher |
| GET | /genealogy/dna-interpretations/{id} | Fetch a DNA interpretation | Client, Researcher, ProjectManager |
| GET | /genealogy/dna-interpretations | List DNA interpretations, filterable | Client, Researcher, ProjectManager |
| POST | /genealogy/dna-interpretations/{id}/interpret | Interpret shared centimorgans into a predicted relationship | Researcher |
| POST | /genealogy/document-requests | Request document retrieval (and optional translation) | Researcher |
| GET | /genealogy/document-requests/{id} | Fetch a document request | Client, Researcher, ProjectManager |
| GET | /genealogy/document-requests | List document requests, filterable | Client, Researcher, ProjectManager |
| POST | /genealogy/document-requests/{id}/update-retrieval | Advance the retrieval dimension | Researcher |
| POST | /genealogy/document-requests/{id}/update-translation | Advance the translation dimension | Researcher |
| POST | /genealogy/heirlooms | Accession an heirloom/archive item | Researcher, ProjectManager |
| GET | /genealogy/heirlooms/{id} | Fetch an heirloom item | Client, Researcher, ProjectManager |
| GET | /genealogy/heirlooms | List heirloom items, filterable | Client, Researcher, ProjectManager |
| POST | /genealogy/heirlooms/{id}/advance | Advance the archive pipeline one step | Researcher, ProjectManager |
| POST | /genealogy/deliverables | Create a deliverable in draft | Researcher |
| GET | /genealogy/deliverables/{id} | Fetch a deliverable | Client, Researcher, ProjectManager |
| GET | /genealogy/deliverables | List deliverables, filterable | Client, Researcher, ProjectManager |
| POST | /genealogy/deliverables/{id}/submit | Submit for client review | Researcher |
| POST | /genealogy/deliverables/{id}/accept | Client accepts; cascades to milestone/project | Client, ProjectManager |
| POST | /genealogy/deliverables/{id}/request-revision | Client requests a revision | Client, ProjectManager |
| POST | /genealogy/milestones | Create a billing milestone | ProjectManager |
| GET | /genealogy/milestones/{id} | Fetch a milestone | Client, Researcher, ProjectManager |
| GET | /genealogy/milestones | List milestones, filterable | Client, Researcher, ProjectManager |
| POST | /genealogy/milestones/{id}/invoice | Invoice a ready milestone | ProjectManager |
| POST | /genealogy/milestones/{id}/record-payment | Record payment on an invoiced milestone | ProjectManager |
| POST | /genealogy/milestones/{id}/cancel | Cancel/credit a milestone | ProjectManager |
| POST | /genealogy/time-entries | Log hours against a project | Researcher |
| GET | /genealogy/time-entries/{id} | Fetch a time entry | Client, Researcher, ProjectManager |
| GET | /genealogy/time-entries | List time entries, filterable | Client, Researcher, ProjectManager |
| POST | /genealogy/time-entries/{id}/void | Void an active time entry | Researcher, ProjectManager |
| POST | /genealogy/appointments | Book a repository visit | Researcher |
| GET | /genealogy/appointments/{id} | Fetch an appointment | Client, Researcher, ProjectManager |
| GET | /genealogy/appointments | List appointments, filterable | Client, Researcher, ProjectManager |
| POST | /genealogy/appointments/{id}/cancel | Cancel an appointment | Researcher, ProjectManager |
| POST | /genealogy/_clock/set_current_utc | Set the server logical clock (test-driving) | ProjectManager |

Filterable list endpoints accept, in addition to `limit` and `offset`: projects by `client_id`, `lead_researcher_id`, and `status`; record searches by `project_id`, `performed_by_id`, and `status`; citations by `project_id`, `person_id`, `record_search_id`, and `verification_status`; persons by `project_id`, `father_id`, `mother_id`, and `verification_status`; DNA interpretations by `project_id`, `subject_person_id`, and `match_person_id`; document requests by `project_id` and `repository_id`; heirlooms by `project_id` and `related_person_id`; deliverables by `project_id` and `milestone_id`; milestones by `project_id` and `deliverable_id`; time entries by `project_id`, `researcher_id`, and `record_search_id`; and appointments by `repository_id`, `project_id`, and `researcher_id`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_FORBIDDEN_NOT_OWNER | 403 |
| ERR_VALIDATION | 400 |
| ERR_CLIENT_NOT_FOUND | 404 |
| ERR_RESEARCHER_NOT_FOUND | 404 |
| ERR_REPOSITORY_NOT_FOUND | 404 |
| ERR_PROJECT_NOT_FOUND | 404 |
| ERR_RECORD_SEARCH_NOT_FOUND | 404 |
| ERR_CITATION_NOT_FOUND | 404 |
| ERR_PERSON_NOT_FOUND | 404 |
| ERR_DNA_NOT_FOUND | 404 |
| ERR_DOCUMENT_REQUEST_NOT_FOUND | 404 |
| ERR_HEIRLOOM_NOT_FOUND | 404 |
| ERR_DELIVERABLE_NOT_FOUND | 404 |
| ERR_MILESTONE_NOT_FOUND | 404 |
| ERR_TIME_ENTRY_NOT_FOUND | 404 |
| ERR_APPOINTMENT_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_PROJECT_NOT_ACTIVE | 409 |
| ERR_CROSS_PROJECT_REFERENCE | 409 |
| ERR_SEARCH_NOT_COMPLETED | 409 |
| ERR_INSUFFICIENT_CITATIONS | 422 |
| ERR_CONFIDENCE_BELOW_THRESHOLD | 422 |
| ERR_SUBJECT_NOT_VERIFIED | 409 |
| ERR_RESEARCHER_UNAVAILABLE | 409 |
| ERR_REPOSITORY_AT_CAPACITY | 409 |
| ERR_INVALID_INTERVAL | 422 |
| ERR_HOURS_CAP_EXCEEDED | 409 |
| ERR_STALE_PROJECT_VERSION | 412 |
