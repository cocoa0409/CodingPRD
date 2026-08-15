# Label & Flexible-Packaging Converter API — Product Requirements Document

## 1. Introduction

A multi-color label and flexible-packaging converter lives between brand owners and the pressroom. Every order arrives as artwork that must be plated, proofed and revised; every job consumes substrate, ink and a cutting die; every finished roll must satisfy the customer's rewind specification before it may ship. Small commercial errors — a forgotten plate charge, a short shipment invoiced at the quoted tier, a tooling charge billed twice or never — compound quickly across thousands of jobs, and one missing food-contact compliance letter can hold an entire shipment at the dock.

This document specifies the Label & Flexible-Packaging Converter API, mounted under `/label-jobs`, which governs that workflow end to end. It covers artwork revision control with automatic supersession, substrate and ink-recipe registration with food-contact attributes, die inventory carrying a one-time new-die tooling charge, press makeready and running-waste allowances that depend on run length, Delta-E color measurement and judgment, rewind-roll splice discipline, and a two-stage pricing model in which a provisional quote produced at order entry is replaced at shipment by a final invoice computed from the quantity actually produced. Work is divided across four operator roles — the commercial desk, prepress, the pressroom and quality — whose hand-offs form the approval chain this API enforces.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes four roles, spelled exactly as follows:

- `Estimator` — the commercial desk: customer accounts, substrates, ink recipes, dies, presses, and job quoting, approval, release and cancellation.
- `PrepressOperator` — prepress: the artwork revision lifecycle (register, submit, approve, return).
- `PressOperator` — the pressroom: starting and completing press runs, and recording color measurements and finished rolls.
- `QualityManager` — quality assurance: judging color measurements, accepting or rejecting rolls, issuing compliance letters, and shipping jobs.

For each of these four roles — `Estimator`, `PrepressOperator`, `PressOperator` and `QualityManager` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it, but it never compares it to any resource's `id`, and no ownership check is derived from it. Authorization is governed purely by the role named in `X-User-Role`. An attempt to perform an operation outside the caller's role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. Read-only retrieval of any resource is available to all four roles.

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

Endpoints that return lists of resources accept two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count` and `has_more`.

### 2.4. Resource Identity and Common Fields

Every resource is identified by an `id`, a server-minted UUID with no type prefix. Alongside it, resources carry `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits (for example, `2025-05-24T10:30:00.123Z`) — and an integer `version` that increments by one on every mutation of the resource, whether the mutation is client-invoked or server-driven. `updated_at` refreshes on the same occasions.

One entity is deliberately lighter: a **ComplianceLetter** is an immutable artifact and carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never modified after issuance.

### 2.5. Request Validation Order and Nested Resource Resolution

Requests are validated in a fixed order, so that an early failure surfaces as itself rather than being masked by a later check:

1. **Authentication context.** The `X-User-ID` and `X-User-Role` headers must be present and well-formed, else the request fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` before anything else is examined.
2. **Authorization.** The declared role must be permitted on the endpoint, else `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Path existence.** Identifiers embedded in the URL are resolved strictly left to right — customer before job, job before measurement, roll or letter — and the first identifier that does not resolve to an existing resource is rejected with `ERR_NOT_FOUND`; deeper identifiers are never examined.
4. **Payload well-formedness.** For requests with a body, every required field must be present, no unknown fields may appear, and all types and enum members must be valid, else `ERR_INVALID_REQUEST`.
5. **State admissibility.** The target resource must be in a state that permits the operation; violations surface as the state-specific errors `ERR_JOB_NOT_QUOTED`, `ERR_JOB_NOT_APPROVED`, `ERR_JOB_NOT_RELEASED`, `ERR_JOB_NOT_ON_PRESS`, `ERR_JOB_NOT_PRINTED`, `ERR_JOB_NOT_REWOUND`, `ERR_JOB_NOT_CANCELLABLE`, `ERR_ARTWORK_NOT_DRAFT`, `ERR_ARTWORK_NOT_SUBMITTED`, `ERR_MEASUREMENT_ALREADY_JUDGED` or `ERR_ROLL_ALREADY_JUDGED`.
6. **Business rules**, evaluated in this order: food-contact component safety, then color approval, then press occupancy and station capacity, then structural limits (roll counts, splice tolerance, revision monotonicity), then referential freshness (approved artwork, active die), then the fiscal gates (minimum order, credit hold), and last of all optimistic concurrency — a stale expected-version value surfaces as `ERR_STALE_VERSION` only after every other applicable check has passed.

### 2.6. Hierarchical Consistency and Automatic State Reconciliation

Not every state change is client-invoked. The server reconciles dependent resources automatically whenever a governing event occurs: approving a new artwork revision retires the previously approved revision of the same artwork code, and that retirement in turn cancels open jobs still referencing the obsolete revision; judging the last outstanding rewind roll of a job can advance the job without any further request. These automatic transitions are real mutations of the affected resources — each one refreshes `updated_at` and increments `version` exactly as an explicit client write would. A client that cached a resource before such a cascade therefore holds a stale version, which is precisely what the optimistic concurrency rules in §2.8 protect against.

### 2.7. Units, Precision and Rounding

All monetary amounts in this API are integer cents; there are no fractional cents anywhere, in requests or in responses. Every computed charge component is rounded up to the next whole cent (ceiling) before the components are summed, and the same ceiling discipline applies to material footage and waste figures, which are expressed in whole feet. Area is measured in MSI — thousands of square inches. The unit conversions used throughout the pricing model are 304.8 millimetres per foot, 25.4 millimetres per inch, and 12 inches per foot. Color error is recorded as a decimal Delta-E 2000 value and judged against a pass limit of 2.0.

### 2.8. Optimistic Concurrency Control

Two write operations guard against stale reads through a mandatory expected-version field:

- **Releasing a job** requires the request body to carry `expected_artwork_version`, holding the `version` of the referenced artwork revision as the client last observed it. If the revision's current `version` has advanced since — for example because a newer revision of the same artwork code was approved in the meantime — the release is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Shipping a job** requires the request body to carry `expected_job_version`, holding the job's `version` as the shipper last observed it. If the job's current `version` has advanced since — for example because a late rewind-roll judgment or a compliance-letter issuance has legitimately mutated the job — the shipment is rejected with `ERR_STALE_VERSION` (HTTP 412).

Both fields are non-optional on the operations that require them, and no other endpoint accepts a version field.

## 3. Business Logic & Workflows

### 3.1. Commercial Setup: Customers, Substrates, Ink Recipes and Presses

An `Estimator` opens the commercial relationship by registering a customer with an `account_name`. Two optional attributes complete the account: `credit_hold` (default false) marks accounts that must not release new work to press, and `preferred_currency` (default `USD`) records the billing currency code. Later account maintenance — most commonly placing or lifting a credit hold — is likewise an `Estimator` operation, and each update increments the customer's `version`.

Materials come next. A substrate is registered with a unique `substrate_code` (for example, BOPP-30 or PET-12), the web `width_mm` available on the roll, a `cost_per_msq_cents` expressing material cost per thousand square inches, and a `food_contact_certified` flag (default false) attesting that the material carries a food-contact certification. An ink recipe is registered with a unique `recipe_code`, a `cost_per_lb_cents` price per pound, and a `food_contact_compliant` flag (default false) declaring the formulation suitable for food-contact packaging. These two flags resurface later as hard gates: a job flagged for food-contact work can be released, and its compliance letter issued, only when both components are qualified.

Presses round out the plant model. Registering a press records a unique `press_code`, the `station_count` — the number of print stations, which caps how many colors the press can run — the `setup_waste_ft`, being the base feet of material consumed in makeready before the first sellable impression, and the `run_waste_pct_numerator`, the running-waste percentage expressed as a numerator: a value of 5 means five percent of the running footage is wasted.

### 3.2. Die Inventory and the New-Die Tooling Charge

Dies enter inventory through one of two `Estimator` capabilities, both taking a unique `die_code`, a free-text `shape_description`, and `cavities_across` — the number of label cavities the die cuts across the web. A die already on the shelf is simply registered: it starts `ACTIVE`, its `new_die_charge_cents` is 0, and its `charge_collected` is false. A die ordered from the toolmaker through the new-die purchase capability also starts `ACTIVE` with `charge_collected` false, but it carries a one-time tooling charge of 750,000 cents (that is, $7,500.00) in `new_die_charge_cents`.

The tooling charge follows the die, not the customer. It is billed exactly once — into the first job released against the die — and if that job is later cancelled, whether explicitly or through artwork supersession, `charge_collected` flips back to false so that the next job to release against the die is billed instead. When a die reaches the end of its useful life, an `Estimator` retires it, moving it from `ACTIVE` to `RETIRED` and incrementing its `version`; retired dies remain visible in inventory but cannot be referenced by newly created jobs, which are rejected with `ERR_DIE_RETIRED`.

### 3.3. Artwork Registration and the Revision Approval Loop

Before any job can be quoted, prepress registers the artwork. A `PrepressOperator` registers each revision under its owning customer — the system records the linkage as the revision's `customer_id` — supplying an `artwork_code` that is unique per customer, a `revision_no`, the `color_count` of print stations the art requires (between 1 and 8 inclusive), and the one-time `plate_set_cost_cents` for that revision's plate set. Revision numbers are strictly monotonic within an artwork code: registration is rejected with `ERR_ARTWORK_REVISION_NOT_MONOTONIC` unless the new `revision_no` is strictly greater than the current maximum revision number registered for the same customer and `artwork_code`. A new revision is born `DRAFT`.

The revision loop is a prepress affair. Submitting a revision moves it `DRAFT` → `SUBMITTED`, and submitting anything that is not `DRAFT` draws `ERR_ARTWORK_NOT_DRAFT`. From `SUBMITTED` there are two exits: approval moves the revision to `APPROVED`, while returning it for rework moves it back to `DRAFT`; both require the revision to currently be `SUBMITTED`, else `ERR_ARTWORK_NOT_SUBMITTED`. Submit, approve and return each increment the revision's `version`.

Approval is a supersession event. Any other revision of the same customer and `artwork_code` that is currently `APPROVED` flips automatically to `OBSOLETE`, so that at most one revision of a code is ever approved at a time. The cascade continues into the order book: every job in `QUOTED`, `APPROVED` or `RELEASED` that still references the now-`OBSOLETE` revision flips to `CANCELLED`, and if such a job had collected the die tooling charge, that charge is released — the die's `charge_collected` returns to false, freeing the charge to be billed to the next job that uses the die. `APPROVED` and `OBSOLETE` are the terminal states of an artwork revision.

### 3.4. Job Quoting and the Provisional Price

With materials, dies and approved artwork in place, an `Estimator` creates a job under its customer — recorded on the job as `customer_id` — by naming the five resources the job binds: `artwork_version_id`, `substrate_id`, `ink_recipe_id`, `die_id` and `press_id`. The order itself is described by `quantity_ordered`, the label `repeat_length_mm` (the cut-off length), the customer's rewind specification `rewind_max_rolls` and `max_splices_per_roll`, and a `requires_food_contact_letter` flag (default false). Two guards apply at creation: the referenced die must not be `RETIRED` (`ERR_DIE_RETIRED`), and the artwork's `color_count` must not exceed the press's `station_count` (`ERR_COLOR_COUNT_EXCEEDS_PRESS`).

A job walks the chain `QUOTED` → `APPROVED` → `RELEASED` → `ON_PRESS` → `PRINTED` → `REWOUND` → `SHIPPED`, with `CANCELLED` reachable from the first three states. At creation the job is `QUOTED`; `material_ft`, `good_quantity_produced` and `invoiced_price_cents` remain unset, `die_charge_applied_cents` starts at 0, and the system computes a provisional `quoted_price_cents` from four components.

The first component is the base print charge, priced by an average-rate tier table keyed on the full `quantity_ordered` — the single applicable rate covers the entire quantity rather than accumulating marginally across brackets. Quantities below 5,000 labels price at 4,500 cents per thousand; quantities of at least 5,000 but below 20,000 price at 3,800 cents per thousand; quantities of 20,000 or more price at 3,200 cents per thousand. The base charge is the ordered quantity divided by one thousand and multiplied by the applicable per-thousand rate, rounded up to whole cents.

The material component needs footage, which is not truly known until release — so the quote assumes the worst case. A provisional running footage is computed exactly as the release-time conversion does it: `quantity_ordered` multiplied by `repeat_length_mm`, divided by 304.8 millimetres per foot, rounded up to a whole foot. The provisional total footage then adds the press's full `setup_waste_ft` unconditionally — the short-run exemption is never assumed at quote time — plus running waste, which is the provisional running footage multiplied by `run_waste_pct_numerator` and divided by 100, rounded up to a whole foot. That footage is converted to area: multiplied by 12 to express web length in inches, multiplied by the web width in inches (the substrate's `width_mm` divided by 25.4 millimetres per inch), and divided by 1,000 to yield MSI. The material charge is that MSI figure multiplied by the substrate's `cost_per_msq_cents`, rounded up to whole cents.

The ink component allows one pound of ink per 5,000 linear feet per print station: the provisional total footage multiplied by the artwork's `color_count` and divided by 5,000 yields pounds of ink, which multiplied by the recipe's `cost_per_lb_cents` and rounded up to whole cents is the ink charge. Finally, one plate set per job adds the artwork revision's `plate_set_cost_cents`. The provisional `quoted_price_cents` is the sum of base, material, ink and plates; the new-die tooling charge is deliberately absent from the quote, because only at release does the system know whether this job is the die's first use.

An `Estimator` then approves the quote, moving the job from `QUOTED` to `APPROVED` — any other starting state draws `ERR_JOB_NOT_QUOTED` — and incrementing the job's `version`. For portfolio visibility beyond the per-customer job list, the cross-customer job listing accepts optional filters `customer_id`, `artwork_version_id`, `substrate_id`, `ink_recipe_id`, `die_id`, `press_id` and `status`, alongside the usual pagination.

### 3.5. Release to Production: Material Calculation and First-Use Die Billing

Release is the commercial point of no return, and the `Estimator` who releases a job must clear five gates. The job must be `APPROVED` (`ERR_JOB_NOT_APPROVED`). The customer must not be on credit hold (`ERR_CUSTOMER_CREDIT_HOLD`). The `quantity_ordered` must be at least the minimum order quantity of 1,000 labels (`ERR_BELOW_MINIMUM_ORDER`). The referenced artwork revision must be `APPROVED` (`ERR_ARTWORK_NOT_APPROVED`). And when the job's `requires_food_contact_letter` is true, both the substrate's `food_contact_certified` and the ink recipe's `food_contact_compliant` must be true (`ERR_FOOD_CONTACT_COMPONENT`). Because a newer artwork revision may have been approved since the releaser last read it — legitimately superseding the referenced one — the release request must also carry `expected_artwork_version` matching the referenced revision's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` as described in §2.8.

At release the system computes and freezes the job's `material_ft` in three steps. First, the running footage: `quantity_ordered` multiplied by `repeat_length_mm` and divided by 304.8 millimetres per foot, rounded up to a whole foot. Second, setup waste: when the running footage is below the short-run threshold of 5,000 feet, the press's full `setup_waste_ft` is charged; when the running footage is 5,000 feet or more, makeready is considered amortized across the run and no separate setup waste is billed. Third, running waste: the running footage multiplied by the press's `run_waste_pct_numerator` and divided by 100, rounded up to a whole foot. The job's `material_ft` is the sum of running footage, setup waste and running waste, and it does not change afterwards.

Release is also the moment the new-die charge finds its first job. If the referenced die carries a positive `new_die_charge_cents` and its `charge_collected` is still false, the full tooling charge is billed into this job as `die_charge_applied_cents`, the die's `charge_collected` flips to true, and the die's `version` increments. A job that releases against a die whose charge was already collected — or that never carried a charge — leaves its `die_charge_applied_cents` at 0. The job itself moves `APPROVED` → `RELEASED`, its `version` incrementing as on every mutation.

### 3.6. Pressroom Execution and Delta-E Color Approval

A `PressOperator` takes a released job onto press; the job must be `RELEASED` (`ERR_JOB_NOT_RELEASED`), and the press must be free — one job at a time per press, so if another job is currently `ON_PRESS` on the referenced press the attempt is rejected with `ERR_PRESS_OCCUPIED`. The job is now `ON_PRESS`.

While the job runs, the operator records Delta-E 2000 readings against the approved color standard, one measurement per station at a time, supplying the `station_no` — from 1 up to the press's `station_count` — and the measured `delta_e`. Recording requires the parent job to be `ON_PRESS` (`ERR_JOB_NOT_ON_PRESS`), and each measurement is born in `PENDING`, tied to its job by the system-recorded `job_id`. Judgment belongs to the `QualityManager`, who supplies a `verdict` of `PASS` or `FAIL` for each pending measurement. Passing a measurement requires its `delta_e` to be at most 2.0; an attempt to judge `PASS` with a higher reading is rejected with `ERR_DELTA_E_EXCEEDS_LIMIT`. Either judgment requires the measurement to still be `PENDING` (`ERR_MEASUREMENT_ALREADY_JUDGED`) and the parent job to be `ON_PRESS` (`ERR_JOB_NOT_ON_PRESS`). Judging increments the measurement's `version`, and `PASS` and `FAIL` are both terminal verdicts.

A `FAIL` verdict does not block the press. The operator may record a replacement measurement for the same station, which simply appends a new `PENDING` row alongside the old one — the failed row stays `FAIL` and never re-opens; color history is revision-by-append rather than overwrite.

Completing the press run is the fork where quality gates the schedule. The `PressOperator` supplies `good_quantity_produced`, which must be present and greater than zero (`ERR_INVALID_GOOD_QTY`), and the color gate evaluates the history revision-by-append: for each station the most recently recorded measurement is that station's record on file, and every such latest-per-station measurement must carry the verdict `PASS` — a superseded row, including one judged `FAIL`, remains on record but does not block completion once a later measurement for the same station has passed — with the further requirement that at least one measurement exists, since an empty measurement log proves nothing (`ERR_COLOR_NOT_APPROVED`). Completion records the good quantity on the job, where it later drives the invoice, and moves the job `ON_PRESS` → `PRINTED`.

### 3.7. Rewind, Compliance Letters and Shipment

Off the rewinder, finished rolls are recorded by the `PressOperator` one at a time, each with its `roll_seq` (the 1-based sequence number of the roll within the job), the `label_count` of good labels wound on, and its `splice_count`. The parent job must be `PRINTED` (`ERR_JOB_NOT_PRINTED`), and the job's roll count may never exceed its `rewind_max_rolls` — recording one roll too many is rejected with `ERR_ROLL_LIMIT_EXCEEDED`. Each roll starts `WOUND` and carries the system-recorded `job_id`.

Roll judgment belongs to the `QualityManager`, and both verdicts require the roll to still be `WOUND` (`ERR_ROLL_ALREADY_JUDGED`) and the parent job to be `PRINTED` (`ERR_JOB_NOT_PRINTED`). Acceptance additionally enforces the customer's splice tolerance: a roll whose `splice_count` exceeds the job's `max_splices_per_roll` cannot be accepted (`ERR_SPLICE_LIMIT_EXCEEDED`). Rejection carries no extra condition. Either way the roll's `version` increments, and after each judgment the server re-checks the job: when every recorded roll has been judged — `ACCEPTED` or `REJECTED` — and at least one is `ACCEPTED`, the job advances automatically from `PRINTED` to `REWOUND`.

For food-contact work, a `QualityManager` issues the compliance letter once the job is `PRINTED` or `REWOUND`; in any other state the request is rejected with `ERR_JOB_NOT_READY_FOR_LETTER`. The letter takes a `letter_type` (only `FOOD_CONTACT` exists) and a free-text `body` asserting substrate and recipe conformity; the server stamps `issued_at` and links the letter to its job via `job_id`. One such letter per job: a second `FOOD_CONTACT` letter is rejected with `ERR_DUPLICATE_LETTER`. Issuance re-applies the component gate — substrate and ink recipe must both be food-contact qualified, else `ERR_FOOD_CONTACT_COMPONENT` — and per §2.4 the issued letter is immutable, carrying neither `updated_at` nor `version`.

Shipment is the final act, performed by a `QualityManager`. The job must be `REWOUND` (`ERR_JOB_NOT_REWOUND`); a job flagged `requires_food_contact_letter` cannot ship until its `FOOD_CONTACT` letter exists (`ERR_COMPLIANCE_LETTER_MISSING`); and the request must carry `expected_job_version` matching the job's current `version`, rejected as `ERR_STALE_VERSION` on mismatch per §2.8. Shipment prices the invoice on what the customer actually receives. The same average-rate tier table as the quote applies — 4,500, 3,800 or 3,200 cents per thousand across the same brackets — but keyed on `good_quantity_produced`, so a run that ships short can fall into a lower bracket and re-price at the higher per-thousand rate: the invoice is not the quote. The base charge is the good quantity divided by one thousand, multiplied by the applicable rate, rounded up to whole cents. Material and ink are recomputed from the `material_ft` frozen at release — reflecting the makeready policy actually applied rather than the quote's worst case — using the same MSI conversion for material and the same one-pound-per-5,000-feet-per-station allowance for ink, each rounded up to whole cents. The final `invoiced_price_cents` is the sum of the base charge, the material charge, the ink charge, the artwork's `plate_set_cost_cents`, and any `die_charge_applied_cents` billed at release; it replaces the provisional quote, and the difference between the two figures is the invoice variance. The job moves `REWOUND` → `SHIPPED`, a terminal state.

### 3.8. Cancellation and the Compensating Die-Charge Release

Until a job goes on press, an `Estimator` may cancel it: cancellation is permitted from `QUOTED`, `APPROVED` or `RELEASED`, and from any other state it is rejected with `ERR_JOB_NOT_CANCELLABLE`. Cancellation is compensating, not merely terminal. If the cancelled job had billed the die tooling charge and is still the die's billing job, the die's `charge_collected` flips back to false and the job's `die_charge_applied_cents` is released, so that the next job released against that die is billed instead. The identical compensating release applies when cancellation is automatic — a job cancelled because its referenced artwork revision was superseded returns its die to the un-billed state in exactly the same way. `CANCELLED` is terminal, alongside `SHIPPED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state transition and customer update — return `200 OK`. The table below is a routing summary only: request payloads, preconditions, calculations and side effects are defined by the workflow narratives in §3, and the authorized roles listed here are enforced as described in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/label-jobs/customers` | Create a customer account | Estimator |
| GET | `/label-jobs/customers` | List customers | Any |
| GET | `/label-jobs/customers/{id}` | Get one customer | Any |
| PATCH | `/label-jobs/customers/{id}` | Update customer flags (e.g., place on credit hold) | Estimator |
| POST | `/label-jobs/customers/{id}/artwork-versions` | Register a new artwork revision under a customer | PrepressOperator |
| GET | `/label-jobs/customers/{id}/artwork-versions` | List a customer's artwork revisions | Any |
| GET | `/label-jobs/customers/{id}/artwork-versions/{artworkId}` | Get one artwork revision | Any |
| POST | `/label-jobs/customers/{id}/artwork-versions/{artworkId}/submit` | Submit a DRAFT revision for approval | PrepressOperator |
| POST | `/label-jobs/customers/{id}/artwork-versions/{artworkId}/approve` | Approve a SUBMITTED revision, superseding the prior APPROVED one | PrepressOperator |
| POST | `/label-jobs/customers/{id}/artwork-versions/{artworkId}/return` | Return a SUBMITTED revision to DRAFT for rework | PrepressOperator |
| POST | `/label-jobs/substrates` | Register a substrate | Estimator |
| GET | `/label-jobs/substrates` | List substrates | Any |
| GET | `/label-jobs/substrates/{substrateId}` | Get one substrate | Any |
| POST | `/label-jobs/ink-recipes` | Register an ink recipe | Estimator |
| GET | `/label-jobs/ink-recipes` | List ink recipes | Any |
| POST | `/label-jobs/dies` | Register an existing die already on the shelf (no tooling charge) | Estimator |
| POST | `/label-jobs/dies/purchase` | Order a new die from the toolmaker, carrying the one-time new-die charge | Estimator |
| GET | `/label-jobs/dies` | List dies | Any |
| GET | `/label-jobs/dies/{dieId}` | Get one die | Any |
| POST | `/label-jobs/dies/{dieId}/retire` | Retire a die; retired dies cannot be referenced by new jobs | Estimator |
| POST | `/label-jobs/presses` | Register a press | Estimator |
| GET | `/label-jobs/presses` | List presses | Any |
| GET | `/label-jobs/presses/{pressId}` | Get one press | Any |
| POST | `/label-jobs/customers/{id}/jobs` | Create a job; computes the provisional quoted price | Estimator |
| GET | `/label-jobs/customers/{id}/jobs` | List one customer's jobs | Any |
| GET | `/label-jobs/jobs` | List jobs across customers with optional filters | Any |
| GET | `/label-jobs/jobs/{id}` | Get one job | Any |
| POST | `/label-jobs/jobs/{id}/approve` | Approve the quote | Estimator |
| POST | `/label-jobs/jobs/{id}/release` | Release the job to production; computes material footage and bills the die's first-use charge | Estimator |
| POST | `/label-jobs/jobs/{id}/start-press` | Put the job on press (one job on press per press) | PressOperator |
| POST | `/label-jobs/jobs/{id}/complete-press` | Finish the press run; requires the latest color measurement per station passed; records the good quantity | PressOperator |
| POST | `/label-jobs/jobs/{id}/ship` | Ship the job; computes the final invoice from the good quantity | QualityManager |
| POST | `/label-jobs/jobs/{id}/cancel` | Cancel a job before it goes on press; releases any die charge billed to it | Estimator |
| POST | `/label-jobs/jobs/{id}/color-measurements` | Record a Delta-E measurement for a print station while on press | PressOperator |
| GET | `/label-jobs/jobs/{id}/color-measurements` | List a job's color measurements | Any |
| POST | `/label-jobs/jobs/{id}/color-measurements/{measurementId}/judge` | Judge a PENDING measurement PASS or FAIL | QualityManager |
| POST | `/label-jobs/jobs/{id}/rewind-rolls` | Record a finished roll off the rewinder | PressOperator |
| GET | `/label-jobs/jobs/{id}/rewind-rolls` | List a job's finished rolls | Any |
| POST | `/label-jobs/jobs/{id}/rewind-rolls/{rollId}/accept` | Accept a WOUND roll (splice limit enforced) | QualityManager |
| POST | `/label-jobs/jobs/{id}/rewind-rolls/{rollId}/reject` | Reject a WOUND roll | QualityManager |
| POST | `/label-jobs/jobs/{id}/compliance-letters` | Issue a food-contact compliance letter for a job (one per job) | QualityManager |
| GET | `/label-jobs/jobs/{id}/compliance-letters` | List a job's compliance letters | Any |

## 5. Error Code Catalogue

The trigger condition for each error lives with the workflow that raises it (see §2 and §3); this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_JOB_NOT_QUOTED` | 409 Conflict |
| `ERR_JOB_NOT_APPROVED` | 409 Conflict |
| `ERR_JOB_NOT_RELEASED` | 409 Conflict |
| `ERR_JOB_NOT_ON_PRESS` | 409 Conflict |
| `ERR_JOB_NOT_PRINTED` | 409 Conflict |
| `ERR_JOB_NOT_REWOUND` | 409 Conflict |
| `ERR_JOB_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_JOB_NOT_READY_FOR_LETTER` | 409 Conflict |
| `ERR_ARTWORK_NOT_DRAFT` | 409 Conflict |
| `ERR_ARTWORK_NOT_SUBMITTED` | 409 Conflict |
| `ERR_ARTWORK_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_MEASUREMENT_ALREADY_JUDGED` | 409 Conflict |
| `ERR_ROLL_ALREADY_JUDGED` | 409 Conflict |
| `ERR_DELTA_E_EXCEEDS_LIMIT` | 422 Unprocessable Entity |
| `ERR_COLOR_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_PRESS_OCCUPIED` | 409 Conflict |
| `ERR_COLOR_COUNT_EXCEEDS_PRESS` | 409 Conflict |
| `ERR_ROLL_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SPLICE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FOOD_CONTACT_COMPONENT` | 422 Unprocessable Entity |
| `ERR_DIE_RETIRED` | 422 Unprocessable Entity |
| `ERR_BELOW_MINIMUM_ORDER` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_CREDIT_HOLD` | 422 Unprocessable Entity |
| `ERR_COMPLIANCE_LETTER_MISSING` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_LETTER` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_GOOD_QTY` | 422 Unprocessable Entity |
| `ERR_ARTWORK_REVISION_NOT_MONOTONIC` | 422 Unprocessable Entity |
