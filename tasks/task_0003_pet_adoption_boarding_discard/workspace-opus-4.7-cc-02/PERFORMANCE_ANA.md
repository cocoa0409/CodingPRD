# Performance Analysis: workspace-opus-4.7-cc-02

**Result: 90/252 (35.7%)**

## Root Causes

### 1. Vaccination record payload field name mismatch — 162 failures (100% of failures)

The implementation defines the vaccination-record create endpoint to require a `vaccine_type` field (app.py:842 `require_fields(body, ['animal_id', 'vaccine_type', ...])`), but the test suite — and every downstream fixture that builds an adoption-eligible animal — sends `vaccine_name` (factories.py:112, assertions.py:55, test_04_vaccination_records.py:30). Every POST `/vaccination-records` call therefore returns `400 ERR_INVALID_REQUEST "Missing fields: vaccine_type"` before any business logic runs. The PRD text lists vaccine identifiers (`RABIES`, `DHPP`, `BORDETELLA`, `FVRCP`, `RHDV`) as uppercase constants but never prescribes the JSON key; the implementation guessed `vaccine_type` while the tests adopted `vaccine_name`. Because an animal cannot become `AVAILABLE` without compliant vaccinations, and because adoption applications, home visits, boarding reservations, compliance holds, invoices, cascades, and end-to-end flows all depend on an `AVAILABLE` or compliant animal, this single field-name mismatch cascades through 12 of 14 test modules. 158 of the 162 failures are setup cascades (`"Setup step failed with HTTP 400"`); the remaining 4 are direct `test_04_vaccination_records` cases where the same field validation fires.

### 2. Validation-order coupling (masked by #1)

`test_create_vaccination_record_nonexistent_animal` expects `ERR_ANIMAL_NOT_FOUND` when `animal_id` doesn't exist, but the implementation returns `ERR_INVALID_REQUEST` because required-field validation runs before the existence check. This would surface as a real defect once #1 is fixed: the correct order is to validate presence of `animal_id`, then resolve the referenced animal, then validate domain-specific fields. Currently invisible behind the `vaccine_type` rejection, but a distinct contract bug.

### 3. Compliance recomputation not triggered on vaccination add (masked by #1)

`test_compliance_recomputed_on_vaccination_add` fails with `assert False is True`. The only non-field failure in `test_04` that reached assertion territory suggests the `vaccination_compliant` flag is not refreshed on the animal resource after a successful record create. Cannot be fully confirmed while #1 blocks the full flow.

## Model Weaknesses

**Unconstrained schema naming.** When the PRD names enum values (`RABIES`, `DHPP`, ...) but omits the JSON key that carries them, the model must commit to a name. It picked `vaccine_type` — semantically reasonable, but wrong against the hidden test contract. The model did not hedge (e.g., accepting both aliases) nor anchor on the PRD's own nearby nouns (the PRD uses the phrase "vaccine" and "vaccination record" but never "vaccine type"). In black-box evaluation, a single wrong guess on a root-entity field silently destroys every downstream test.

**Validation-ordering blind spot.** The generic `require_fields` pattern is applied uniformly, so path-parameter/body-reference existence checks are subordinated to presence checks. The model did not recognize that entity-resolution errors should take precedence over body-shape errors when the body references a foreign key by id.

**Dependency-graph under-weighting.** The vaccination record is a single endpoint but it sits at the root of the adoption/boarding dependency tree. The model treated it with equal care to leaf resources, missing that any defect here produces outsized damage. A more robust strategy would over-invest in verifying root-entity contracts before moving on.

## What Passed

The 90 passing tests concentrate in resource-CRUD modules that don't require vaccination-compliant animals: shelter CRUD (11), adopter CRUD (14), fee schedules (11/11 — clean), animal CRUD basics (17), and the RBAC tests that hit permission boundaries before business logic (19). One-off passes appear in modules whose happy paths don't traverse a fresh vaccination record. The implementation's shelter, fee-schedule, and adopter surfaces look structurally correct; its animal/workflow layer is almost entirely untested because vaccination is the mandatory prerequisite and the prerequisite endpoint is unreachable.
