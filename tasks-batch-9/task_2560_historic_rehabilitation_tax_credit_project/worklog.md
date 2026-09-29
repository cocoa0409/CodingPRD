# Worklog — task_2560_historic_rehabilitation_tax_credit_project

## Step 1: Create task directory — 2026-09-03T10:25:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2560_historic_rehabilitation_tax_credit_project` and its `workspace/` subdirectory. Index 2560 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-03T11:48:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2560_historic_rehabilitation_tax_credit_project/SCAFFOLD.yaml` | 3145 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2560_historic_rehabilitation_tax_credit_project/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1946 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2560_historic_rehabilitation_tax_credit_project/SCAFFOLD_CORNER_DESIGN.yaml` | 4071 |

`SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; each design file has exactly one top-level key.

## SCAFFOLD.yaml counts (§1.0–§1.7)
12 entities · 9 state machines · 2 §1.2.1 OCC rules · 7 calculations · 38 ordered validations · 47 endpoints · 46 errors · 6 roles (all with `identity:`). `domain_name: historic-rehab-tax-credit`, `api_prefix: ""`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers `dual_variant_calculation / rate_threshold_triggers / cascading_side_effects / optimistic_concurrency`.

## §1.8 — depth probe
9 `rule_id`s × 2 instances = **18 instances**, all with full structured `setup_api_calls`.

## §1.9 — breadth probe
**9 sections, 81 instances (62 with `test_recipe`, 19 `excluded_because` stubs):** entities 13 · state_machines 12 (3 stubs) · calculations 13 (7 stubs) · validations 10 (4 stubs) · endpoints 5 · errors 14 · rbac 5 · cross_cutting_complexity_layers 8 (5 stubs) · consistency_model 1.

All 46 §1.6 error codes are now referenced by at least one §1.8/§1.9 instance (verified programmatically); all 81 names are unique across the union of both design files; every stub cites a `difficulty_instance` that exists by name in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and carries no `test_recipe`; every `claim_type` comes from `references/claim-extraction-guide.md` rows.

## Design adjudications made this session
1. **`ERR_SEGREGATION_OF_DUTIES` was unreachable.** `Reviewer.agency` is `SHPO|NPS` only, so the reviewer whose id equals `shpo_reviewer_id` would also fail the priority-50 agency check — two rules in the same band with no pinned order. Fixed in `SCAFFOLD.yaml` by pinning the intra-priority-50 order: the identity-reuse check runs *before* the agency check on `POST /part-applications/{id}/nps-determination`. That yields a clean complementary pair in §1.9/rbac (same reviewer → `ERR_SEGREGATION_OF_DUTIES`; a *different* SHPO-agency reviewer → `ERR_UNAUTHORIZED`).
2. **`ERR_DISQUALIFICATION_RISK_TOO_HIGH` is only reachable via the filing branch** (max ADMISSION score for a non-disqualified party is 62 vs `HIGH_RISK_THRESHOLD` 70; tax-exempt/governmental lessees are intercepted earlier by `ERR_DISQUALIFIED_PARTY`). Both instances therefore use `POST /credit-claims/{id}/file`, and the boundary is probed as a pair: 30-year lease → 69 (files successfully) vs 31-year lease → 70 (rejected).
3. **Errors-section `claim_type`** — the guide's Table 6 has no row vocabulary (only "verify every error code is triggerable"), so `error_triggerable` is used for that section rather than borrowing a Table 4 slug.
4. **Bundling** — the seven remaining 404s share one instance (`..._return_not_found`), and the two claim-year guards share one instance, since each is a single-call probe against the same fixture.
5. **Inactive complexity layers** (`pagination_with_filtering`, `soft_delete`, `idempotency`, etc.) are skipped without ceremony, per the guide; only the four declared layers produce instances.
6. Instance renamed to `request_missing_x_user_id_header_...` so the linter's `_NEGATIVE_NAME_RE` recognises the deliberate role/payload violations (`as: Anonymous`, invalid enum) in that negative test.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2560_historic_rehabilitation_tax_credit_project/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2560_historic_rehabilitation_tax_credit_project/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2560_historic_rehabilitation_tax_credit_project/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    47
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  944

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Also confirmed: no forbidden concurrency vocabulary ("simultaneously", "at the same time", "concurrently submitted", "in parallel", "first-writer-wins", "race winner/loser") and no unevaluated `round(...)` expressions anywhere in the three files; every OCC `expected_project_version` payload value is a `${var}`. No sibling task directory was read at any point.

## Step 3: Copy Shared Files — 2026-09-03T11:49:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2560_historic_rehabilitation_tax_credit_project/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T12:05:00.000Z

PRD.md is complete and verified.

## Deliverable

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2560_historic_rehabilitation_tax_credit_project/workspace/PRD.md`
**Final line count: 423 lines** (written as 1 `Write` + 7 `cat >> <<'PRDEOF'` appends; final `tail -20` confirms the file ends on the last complete row of the §5 table — a genuine section boundary, no truncation).

## Sections

- `# Historic Rehab Tax Credit API — Product Requirements Document`
- **§1 Introduction** — paperwork-density framing, compliance-audit → ledger-reconciliation arc, two design commitments
- **§2 Global Specifications** — 2.1 Role-Based Access Control (all 6 roles, entity-backed vs opaque identity translation, agency match, segregation of duties) · 2.2 API Response Structure (verbatim fixed block; `diff` against `section-2.2-response-structure.md` clean) · 2.3 Pagination · 2.4 Common Resource Properties and the Logical Clock (incl. `Developer`/`Reviewer` carrying only `id`+`created_at`) · 2.5 Money, Percentages and Rounding Discipline · 2.6 The Two Independent State Dimensions of a Project (full `compliance_posture` precedence ladder) · 2.7 Cascade Propagation and Version Accounting · 2.8 Optimistic Concurrency on the Project Record · 2.9 The Order in Which a Request Is Rejected (12 precedence bands) · 2.10 Reference Resolution and Sub-Resource Reads · 2.11 Dates, Windows and Interval Semantics
- **§3 Business Logic & Workflows** — 3.1 Seeding the Cast · 3.2 Opening a Project and Fixing the Measuring Period · 3.3 Part-by-Part Applications · 3.4 Recommendation, Findings, Binding Determination · 3.5 Amendments and Two-Agency Concurrence · 3.6 Cost Segregation, Substantial Rehabilitation Test, Credit Schedule · 3.7 Investor Structure and Disqualification Risk · 3.8 Placed in Service, Covenant Monitoring, Recapture · 3.9 Claiming the Credit and Settling Recapture
- **§4 Endpoint Definitions** — 47 rows, exactly 4 columns
- **§5 Error Code Catalogue** — 46 rows, exactly 2 columns

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** All 122 `entities[].fields[].name` present verbatim in backticks; all 88 `request_body`/`input`/`query_params`/`path_params` identifiers present. Zero misses. (A first automated pass reported false misses — naive backtick pairing was desynchronized by the fences in §2.2; re-run with fenced blocks excised: 0 misses.)

**Contract 2 — Rule Coverage: PASS.** 38/38 validations rendered with their `error_id`, priority band, and `applies_to` scope; 9/9 state machines with all states and all 39 transitions (every from/to state named); 7/7 calculations (`qre_totals`, `substantial_rehabilitation_test`, `ratable_credit_schedule`, `investor_disqualification_risk`, `recapture_assessment`, `claim_settlement`, `compliance_posture`) with dual variants, thresholds, rounding modes and pinned step order; 2/2 OCC rules; all cascade side effects with order-sensitivity stated as normative; sibling-branch symmetry preserved. 46/46 errors appear in prose; §5 statuses match the scaffold exactly (0 mismatches); §4 method+path set matches the 47 scaffold endpoints exactly (0 missing, 0 extra) and per-endpoint authorized-role sets match with 0 mismatches.

**Contract 3 — §3 Path Purity: PASS.** 888 backticked spans in §3; zero start with `/`, zero are bare HTTP methods, zero combine method+path, zero contain a `/` at all. Operations are named by state pair (`SHPO_REVIEW -> NPS_REVIEW`), role+action verb, or capability.

Also scanned clean: no fuzzy quantifiers ("approximately"/"roughly"/"conservatively"), no pseudocode or operator syntax, and no meta-commentary — no mention of difficulty levels, scaffold internals, test design, or the pipeline anywhere in the file. Hard constraint honored: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

## Doc-generation adjudications

Several scaffold preconditions carry no assigned `error_id`; the semantically exact existing code was attached so behavior is uniquely determined without revealing test answers:

- `DISTRICT_NONCONTRIBUTING` submit block -> `ERR_PROPERTY_NOT_CERTIFIED_HISTORIC`
- Part 3 submit requires `placed_in_service_date` -> `ERR_PROJECT_NOT_PLACED_IN_SERVICE`
- Part-application creation on a `DECERTIFIED` project -> `ERR_PROJECT_INVALID_STATE`
- `APPROVED` determination with unresolved conditions (and symmetrically `CONDITIONAL` with none) -> `ERR_PART_APPLICATION_INVALID_STATE`
- Part 3 determination substantial-test re-check -> `ERR_SUBSTANTIAL_TEST_NOT_MET`
- Resubmit with reviewer no longer `ACTIVE` -> `ERR_REVIEWER_NOT_ELIGIBLE`; resubmit capacity -> `ERR_REVIEWER_WINDOW_CAPACITY`
- Amendment-submit's Part-2 `CONDITIONAL`-or-`APPROVED` requirement -> `ERR_AMENDMENT_INVALID_STATE`
- Recapture event on `COMPLIANT_CLOSED` -> `ERR_RECAPTURE_OUTSIDE_COMPLIANCE_PERIOD`
- Claim create/file on `RECAPTURED` -> `ERR_PROJECT_INVALID_STATE`

Two further resolutions: `MAX_REVIEW_ROUNDS` ("rejects `review_round` > 3") was rendered under the only non-dead reading — the increment applies first, so a resubmission whose resulting `review_round` would exceed three is refused with `ERR_PART_APPLICATION_INVALID_STATE`. And unit-bearing constants were rendered as prose conversions rather than bare integers ("five thousand dollars expressed in cents", "eighty percent of the building's thirty-nine-year useful life, truncated downward to a whole number of years") — lossless, but requiring the implementer to do the arithmetic rather than copy a worked figure.

**Orchestrator truncation check (per pipeline directive):** independently verified — `wc -l` 423 / 90012 bytes; `grep -c "^| \`ERR_"` = 46 matches the scaffold's 46 declared errors; §4 contains exactly 47 method rows; the file's last line is a complete `| \`ERR_RECAPTURE_OUTSIDE_COMPLIANCE_PERIOD\` | 422 |` table row terminating the §5 catalogue. Not truncated; no regeneration needed.

## Step 6: Generate Implementation — 2026-09-03T12:45:30.000Z

Implementation complete for task 2560.

## Files (`workspace/implementation/`, 3114 lines total)

| File | Lines |
|---|---|
| `start.sh` (executable) | 10 |
| `requirements.txt` | 1 |
| `clock.py` | 60 |
| `errors.py` | 68 |
| `response.py` | 56 |
| `db.py` | 68 |
| `validate.py` | 190 |
| `calc.py` | 227 |
| `services.py` | 361 |
| `auth.py` | 70 |
| `support.py` | 38 |
| `app.py` | 83 |
| `routes/__init__.py` | 0 |
| `routes/identity.py` | 178 |
| `routes/projects.py` | 323 |
| `routes/part_applications.py` | 462 |
| `routes/costs.py` | 161 |
| `routes/amendments.py` | 247 |
| `routes/investors.py` | 275 |
| `routes/compliance.py` | 236 |

## Verification

- Every module `py_compile`s clean; every file ends at a real statement boundary.
- **Endpoint parity is exact**: dumped Flask's `url_map` (method + normalised path) and diffed it against the 47 rows extracted from `SCAFFOLD.yaml`'s `endpoints:` block — `IDENTICAL`, 47/47, no extras, no gaps.
- Storage is in-memory dicts in `db.py` only. No SQLite, no JSON dump, no `/tmp` cache, no seeding — `store` starts empty on every boot.
- Smoke-tested on `PORT=18560` across two runs (~110 assertions, all green), covering: envelope shape for object/array/error, clock advance, the full Part 1->2->3 gauntlet, the finding -> CONDITIONAL determination -> amendment fork-join (SHPO then NPS concur) -> finding RESOLVED -> application APPROVED -> certification advance cascade, developer-fee cap, place-in-service, master-lease vs single-tier structure rejections, election window, allocation ceiling, cost locking at Part 3, claim settlement waterfall and ledger invariant (`claimed+recaptured+unclaimed == total`), covenant breach->cure cycle with investor re-scoring, recapture assessment, and the auditor-disallowance -> `SUBSTANTIAL_TEST_FAILURE` SYSTEM_DERIVED cascade (claim -> ADJUSTED, `CURE_PENDING`). Server was stopped by the exact pid from `lsof -ti tcp:18560`; no broad pkill was ever issued and `__pycache__` was removed.

## Adjudications where PRD wording required a judgement call

Ordering was taken from §2.9's twelve bands wherever §3.x prose disagreed:

1. **`POST /credit-claims/{id}/file`** — §3.9 prose lists the interest check after the state checks, but §2.9 puts investor standing in band 6 and state in band 8, so `ERR_INVESTOR_NOT_ADMITTED` precedes `ERR_CREDIT_CLAIM_ALREADY_FILED`. Within band 10 §2.9's list order is followed: `ERR_DISQUALIFICATION_RISK_TOO_HIGH` **before** `ERR_PASS_THROUGH_ELECTION_REQUIRED`; `ERR_SUBSTANTIAL_TEST_NOT_MET` last.
2. **`POST /part-applications/{id}/findings` does no reviewer agency/credential check** — priority 50 (reviewer agency match) names only `shpo-recommend`, `nps-determination` and `amendments/{id}/concur`, so findings are role-gated only.
3. **Client-supplied `SUBSTANTIAL_TEST_FAILURE`** is rejected at band 3 (the enum admits only the four client types), so it fires before `ERR_PROJECT_NOT_FOUND`.
4. **Covenant window/period coherence is band 11**, so `ERR_PROJECT_NOT_PLACED_IN_SERVICE` (band 8) reports first on a covenant with both problems; the BREACHED cure-deadline check is band 8 (`ERR_COVENANT_INVALID_STATE`), so a late cure outranks a stale period.
5. **`MASTER_LEASE` projects also admit `DIRECT_PARTNER`** interests; only the lessee slot is unique (at most one across all statuses) and only it requires `lease_term_years`.
6. **Amendment concur with an already-resolved/waived finding** still lands — the catalogue assigns no error to that precondition, so the resolution hop is skipped silently.
7. **`COMPLIANT_CLOSED` is not entered vacuously** — a project with zero covenants never closes; posture is implemented as targeted transitions guarded by the absorbing states rather than a blanket re-derivation.
8. **SYSTEM_DERIVED `SUBSTANTIAL_TEST_FAILURE` `event_date`** = the logical-clock date.
9. **`recapture_pct` and `credit_allocation_pct` serialise as JSON numbers** (`float`); the exact `Decimal` allocation is kept in a private `_pct` key for the 100.00% aggregate test.
10. **Version accounting** — `Property.open_project_count` is derived on read (project creation does not bump the property), and re-scoring/flag-refresh helpers bump `version` only when a value actually changes; the election and admission paths bump the interest and project exactly once each.

## Step 5: Generate Unit Tests — 2026-09-03T13:24:00.000Z

Generation complete and verified. All files py_compile clean, all end at real statement boundaries, and `pytest --collect-only` collects 97 tests in 0.37s (pycache/pytest_cache removed afterwards).

## Per-file line counts

`/home/ubuntu/github/CodingPRD/tasks/task_2560_historic_rehabilitation_tax_credit_project/test_helpers/` — 9 files, 2688 lines
- `__init__.py` 92, `api_client.py` 686, `api_errors.py` 186, `assertions.py` 300, `constants.py` 220, `factories.py` 196, `fixtures.py` 391, `test_users.py` 106, `types.py` 511

`.../test_suite/` — 19 files, 5675 lines
- `conftest.py` 27
- Queue A (difficulty): `test_01_dual_variant_calculations.py` 294, `test_02_combinatorial_formulas.py` 222, `test_03_non_linear_state_machines.py` 238, `test_04_transitive_cascades.py` 303, `test_05_priority_pair_validation_conflicts.py` 224, `test_06_boundary_precision.py` 275, `test_07_cross_entity_state_dependencies.py` 221, `test_08_resource_temporal_overlap.py` 236, `test_09_compensating_invariants.py` 261
- Queue B (corner): `test_10_entities.py` 539, `test_11_state_machines.py` 553, `test_12_calculations.py` 380, `test_13_validations.py` 268, `test_14_endpoints.py` 305, `test_15_errors.py` 785, `test_16_rbac.py` 259, `test_17_cross_cutting_complexity_layers.py` 214, `test_18_consistency_model.py` 71

## Total tests: 97
Queue A 36 (18 instances x 2), Queue B 61 (one test per translated instance).

## Coverage audit (independent verifier over both design yamls)
- Difficulty: 18/18 instances covered, 0 with fewer than two tests.
- Corner: 61/62 non-stub instances covered (the 19 `excluded_because:` stubs untranslated, as specified).
- Citation checks: 0 bad/non-verbatim PRD quotes, 0 tag problems (exactly one trailing `Design:` line per test), 0 unresolved tags, 0 references to the scaffold or §1.x anywhere.

Skipped instance (1):
- `Corner/validations/covenant_window_end_not_after_start_is_rejected` — the instance asserts `ERR_INVALID_REQUEST` (400) and explicitly `error_id != ERR_PROJECT_NOT_PLACED_IN_SERVICE` on a project that was never placed in service. PRD §2.9 puts entity-state (`ERR_PROJECT_NOT_PLACED_IN_SERVICE`, band 8) strictly ahead of the covenant-window coherence check (band 11), so the PRD uniquely derives the opposite outcome to the one asserted. Non-derivable as written; skipped rather than weakened or re-set-up (its negative assertion is the whole point of the instance).

## Adjudications (design-index vs PRD conflicts resolved in the PRD's favour, instance still translated)
1. `PART_ALREADY_CERTIFIED`: design said 422, PRD status table says 409 -> asserted 409.
2. Design assertions on `success == false`: the §2.2 envelope has no `success` field -> asserted `response_type == "error"` plus `error_id`/`message`.
3. A 25-year `TAX_EXEMPT_ORG` lease would trip `DISQUALIFICATION_RISK_TOO_HIGH` in the same band as the intended `DISQUALIFIED_PARTY` -> used `lease_term_years=2` (score 69) so exactly one refusal can fire.
4. Late-cure attestation instance had no clock move -> set the clock to 2029-05-10 so band 11's `ERR_INVALID_REQUEST` cannot pre-empt `COVENANT_INVALID_STATE`.
5. Design expected `Property.evaluation_status == UNDER_EVALUATION`, not a declared enum value -> asserted `UNEVALUATED` per §3.x.
6. "No clock advance between the write and the reads" is meta -> expressed as `certified_at.startswith("2026-09-01T00:00:00")`.
7. Exact `...T00:00:00Z` timestamp literals are not uniquely derivable (§2.4 mandates three fractional digits) -> prefix assertions throughout.
8. Two fabricated/weak PRD quotes found during self-audit (a finding-field sentence and the band-6 heading fragment "Ownership and actor identity.") were replaced with real §3.4 line-214 and §2.1 sentences.
9. A settlement quote in the risk-too-high test was off-topic (no settlement occurs when filing is refused) -> replaced with the claim-snapshot sentence.

The generator did not read, run, or touch `workspace/implementation/`, and no server was started.

## Step 7: Run Tests and Iterate — 2026-09-03T13:45:00.000Z

All 8 rounds clean. Leaving the results files in place.

## Summary

**Iterations run:** 2

**Tests deleted:** none. The single failing test passed both STEP 1 sub-checks and STEP 2, so it was a genuine implementation defect.

**Fixes applied to `test_helpers/`:** none. The fixtures were already PRD-faithful — `factories.investor_interest_payload` defaults `structure_type` to `SINGLE_TIER` in `project_payload`, and `fixtures.claim_filed_project` already branches on `structure_type` to pick `admit_master_lease_lessee` vs `admit_direct_partner`, so no direct-partner admission was ever aimed at a master-lease project except in the test that intends to be refused.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/investors.py`, `create_interest()` — the structure-coherence block (PRD band 10) was asymmetric: it rejected `MASTER_LEASE_LESSEE` on a `SINGLE_TIER` project, but the `DIRECT_PARTNER` branch only checked for a forbidden `lease_term_years` and never checked the project's `structure_type`. A `DIRECT_PARTNER` interest on a `MASTER_LEASE` project was therefore admitted with 201 instead of being refused. Added the missing `if master_lease: raise ERR_STRUCTURE_TYPE_MISMATCH` guard.

**Diagnostic trace for the one failure** (`test_15_errors.py::test_a_master_lease_project_refuses_a_direct_partner_interest`, failing 8/8 rounds with `Expected response_type 'error', got 'object'`):
- STEP 1a — PRD §3.7 verbatim: *"Structure coherence is checked against the project's `structure_type`. A `MASTER_LEASE` project admits exactly one `MASTER_LEASE_LESSEE` interest and requires `lease_term_years` on it; a `SINGLE_TIER` project admits only `DIRECT_PARTNER` interests and rejects `lease_term_years` outright. A mismatched `kind`, a missing or forbidden lease term, or a second master-lease lessee is refused with `ERR_STRUCTURE_TYPE_MISMATCH`."* Covered.
- STEP 1b — unique derivability holds. "A mismatched `kind`" presupposes a structure->kind mapping, and PRD pins that mapping from three directions: §3.2 *"This election is what later constrains which kind of investor party may be admitted"*, §3.7's definition *"a `DIRECT_PARTNER` is a partner in a single-tier pass-through"*, and the §3.7 coherence sentence itself. No PRD-faithful reader arrives at "a master-lease project also admits direct partners".
- STEP 2 — the test is faithful: `MASTER_LEASE` project opened by the owning `Developer` (an authorized admitting role per §3.7), payload with no `lease_term_years`, asserting `ERR_STRUCTURE_TYPE_MISMATCH`/422 per the §5 catalogue.
- STEP 3 — implementation fixed as above.

**Final sweep, per-round figures** (quoted from `workspace/implementation/results.{1..8}.json`):

| round | passed / total |
|---|---|
| 1 | 97 / 97 |
| 2 | 97 / 97 |
| 3 | 97 / 97 |
| 4 | 97 / 97 |
| 5 | 97 / 97 |
| 6 | 97 / 97 |
| 7 | 97 / 97 |
| 8 | 97 / 97 |

No flakiness surfaced across the 8 parallel rounds — the pre-fix failure was deterministic (8/8) and the post-fix pass is deterministic (8/8). No reaping signature (no `Terminated` in server logs, all rounds ran to completion).

**Orchestrator verification of sweep artifacts (per pipeline directive):** independently confirmed on disk — all 8 `results.{1..8}.json` exist (~29 KB each, mtime 13:35), each parses with `passed == total == 97`, `failed == 0`, `errors == 0`; `grep -c Terminated workspace/sweep.log` = 0. Step 8 does NOT skip: Step 7 applied 1 `implementation/` fix.

## Step 8: Finalize PRD — 2026-09-03T13:53:00.000Z

`PRD_FINALIZED.md` produced with exactly one edit.

## Line counts
- `PRD.md`: 423 lines; `PRD_FINALIZED.md`: 423 lines — **0.0% line delta** (one line revised in place, §3.7 / line 268).

## Changes
- **§3.7 (The Investor Structure and Its Disqualification Risk) — revise — the structure-coherence sentence was symmetrized: `MASTER_LEASE` now reads "admits only `MASTER_LEASE_LESSEE` interests — exactly one of them —" (previously only "admits exactly one `MASTER_LEASE_LESSEE` interest", which pinned the count but never excluded direct partners), and "A mismatched `kind`" is now spelled out in both directions — `workspace/implementation/routes/investors.py:80-90` (the `else`/`DIRECT_PARTNER` branch containing the Step 7-added `if master_lease: raise ERR_STRUCTURE_TYPE_MISMATCH`).**

Rationale for patching rather than declaring a no-op: the original implementation generator read the same §3.7 prose and produced an *asymmetric* guard, admitting a `DIRECT_PARTNER` onto a `MASTER_LEASE` project with 201. The old sentence's asymmetric phrasing ("admits exactly one X" for one structure vs. "admits only Y" for the other) is exactly what a fresh implementer can read as a cardinality constraint rather than an exclusivity constraint, so this is a genuine PRD under-determination, not a pure fixture bug.

## Pre-edit search log (edit 1, the only edit)
- **(a) Subject identified:** the coherence relation between a project's `structure_type` and an admitted interest's `kind` — i.e. which kinds a project of each structure may hold, and which `ERR_STRUCTURE_TYPE_MISMATCH` conditions exist.
- **(b) Impl paths enumerated (grepped `structure_type|MASTER_LEASE|DIRECT_PARTNER|lease_term` across all of `implementation/`, then read each hit):**
  - `routes/investors.py:63-90` `create_interest()` — the only creation path for an interest; both branches read in full, including check ordering within band 10 (kind mismatch -> missing/forbidden lease term -> duplicate lessee), then `ERR_DISQUALIFIED_PARTY`, then risk, then band-12 allocation. Confirmed all three refusals share one error id, so the sub-ordering inside the branch is unobservable and the wording need not pin it.
  - `routes/investors.py:34-38` `_lessee_of()` — the duplicate-lessee probe; status-agnostic. The "exactly one" / "a second master-lease lessee" clauses were left semantically untouched precisely so this path is not re-described.
  - `routes/investors.py:92-95` — `ERR_DISQUALIFIED_PARTY` gate and the `pass_through_election` default (`PENDING` vs `NOT_APPLICABLE`), both keyed on `kind` alone, not on `structure_type`.
  - `routes/investors.py:244-247` `file_claim()` — `structure_type == "MASTER_LEASE"` requires a lessee with `pass_through_election == "ELECTED"`, treating `lessee is None` as the same failure. Consistent with (indeed reinforced by) "a `MASTER_LEASE` project admits only `MASTER_LEASE_LESSEE` interests".
  - `routes/investors.py:135-159` `elect_pass_through()` — gates on `pass_through_election != "PENDING"`, not on `structure_type`; unaffected.
  - `routes/projects.py:26,69,90` — `structure_type` is a create-time enum election only; no other endpoint mutates it, so no project can change structure under an already-admitted interest.
  - `services.py:200-209` `disqualify_master_lessees()` and `services.py:190-197` `rescore_in_service()` — both filter on `kind`/`status`, never on `structure_type`.
  - `calc.py:184-192` `lease_term_points()` / `calc.py:194-201` `base_risk_score()` — lease-term scoring keyed on `kind == "MASTER_LEASE_LESSEE"` and a non-null `lease_term_years`, independent of project structure.
- **(c) Wording adjustment made to keep all enumerated paths consistent:** two deliberate softenings. First, "exactly one of them" was kept as an em-dash aside rather than rewriting the duplicate-lessee clause, so the status-agnostic `_lessee_of` semantics (a `DISQUALIFIED` lessee still blocks a second admission) stay exactly as under-determined as in `PRD.md` — widening there would have been an out-of-scope new claim. Second, the mismatch gloss is phrased as offered-kind-vs-project-structure ("a `DIRECT_PARTNER` offered to a `MASTER_LEASE` project") without asserting any ordering against the lease-term or duplicate-lessee checks, since all three emit the same error id and pinning an order would be an unverifiable universal claim.

## Step 9: Complete PRD — 2026-09-03T14:20:00.000Z

**Orchestrator decision (recorded per the AUTONOMY directive):** Step 9 was run as **three sequential file-partitioned passes** over one shared `PRD_COMPLETED.md`, rather than a single subagent. Rationale: `implementation/` is 3114 lines across 20 modules and a single scanning agent reliably runs out of working context part-way, which produces a `PRD_COMPLETED.md` nearly byte-identical to its source — the signature of a scan that never really happened. Partitioning by impl file guarantees every module is walked by an agent that still has context budget for it, and passing each pass the previous pass's explicit deferral list preserves the cross-file coherence a single pass would have given. Pass A created the file from `PRD_FINALIZED.md`; Passes B and C were told explicitly not to re-copy it (a re-copy would silently discard the prior pass's edits).

Partition:
- **Pass A** — `app.py`, `auth.py`, `clock.py`, `db.py`, `errors.py`, `response.py`, `support.py`, `validate.py`, `routes/identity.py`, `routes/projects.py`
- **Pass B** — `routes/part_applications.py`, `routes/amendments.py`, `routes/costs.py` + the QRE / substantial-test / ratable-schedule parts of `calc.py`
- **Pass C** — `routes/investors.py`, `routes/compliance.py`, `services.py`, + the investor-risk / recapture / claim-settlement parts of `calc.py`, plus every item Passes A and B deferred

### Pass A — core modules, identity, projects

Created `PRD_COMPLETED.md` from `PRD_FINALIZED.md` (423 lines / 90,159 chars -> 423 lines / 94,651 chars, **+4,492 chars**). 17 in-place line replacements, no lines added/removed, no new sections. **ambiguity-pins: 15 · mismatch-revisions: 5.**

- §2.1 (¶ headers) — insert — ambiguity — a whitespace-only `X-User-ID` counts as empty (401), and an omitted or unrecognised `X-User-Role` is `ERR_UNAUTHORIZED` — `auth.py:20-38`
- §2.1 (ShpoReviewer) — revise — mismatch — reviewers may **not** read the developer identity record, nor the single-resource reads of interests/claims/events/covenants (PRD said "except the investor-side and ledger sub-resource *listings*") — `routes/identity.py:95`, `routes/projects.py:38`, `routes/investors.py:23`, `routes/compliance.py:34-35`
- §2.1 (InvestorAdmin) — revise — mismatch — read scope also covers part applications and the QRE summary, excludes reviewers/costs/findings/amendments, and the one-project scoping binds writes only (reads are unscoped) — `routes/projects.py:227`, `routes/part_applications.py:32-39`, `routes/projects.py:276`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 uppercase-alphanumeric chars — `response.py:10-14`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads from the logical clock, not the wall clock, so it is static between requests — `response.py:17-24`
- §2.3 — insert — ambiguity — a non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`, `offset` has no upper bound, an empty string reads as the default — `validate.py:130-151`
- §2.3 — insert — ambiguity — `created_at` ties break by creation order, and ties are the norm because the clock is frozen — `db.py:66-68`
- §2.4 — revise — mismatch — the "computed fields refresh `updated_at`" claim is narrowed to *stored* fields; a read-time derived field (only `open_project_count`) changes without mutating its row — `services.py:59-60`, `routes/projects.py:116`
- §2.4 — insert — ambiguity — `to_iso8601` accepts any ISO instant (`Z`/offset normalised, naive read as UTC), `data` holds `current_utc` alone, sub-millisecond precision truncated on render — `clock.py:14-33,53`
- §2.4 — insert — ambiguity — the clock control also tolerates a request with no `X-User-Role`; only a non-`PlatformAdmin` declared role is refused — `routes/identity.py:48-50`
- §2.8 — insert — ambiguity — `expected_project_version` is schema-validated as a non-negative integer first, so a bad value is 400 not 412 — `routes/projects.py:148`
- §2.10 — insert — ambiguity — only `tax_year`/`part_number`/`standard_number` are integer-parsed; other filters are exact-equality and are **not** enum-validated, so an unknown value yields an empty page rather than 400 — `support.py:35-38`, `routes/projects.py:265-321`, `validate.py:154-168`
- §2.11 — insert — ambiguity — month arithmetic clamps to the target month's last day when the day of month does not exist — `calc.py:70-76` (called from `routes/projects.py:80,169`)
- §3.1 — insert — ambiguity — `contact_email` max 320 chars and present-as-null when omitted — `routes/identity.py:76,86`
- §3.1 — revise — mismatch — `open_project_count` is derived per read; opening/decertifying a project leaves the property's `updated_at`/`version` untouched, and only an evaluation-outcome change ever mutates a property — `services.py:45-60`, `routes/projects.py:116`
- §3.2 — insert/revise — ambiguity + mismatch — a revision may carry only `expected_project_version` (accepted no-op); the revised project is excluded from the overlap comparison; the ripple runs on **every** accepted revision (not only window moves); only cost items whose `in_measuring_period` flag actually turns over are mutated — `routes/projects.py:144-184`, `services.py:82-89`
- §3.6 — insert — ambiguity — an unrecognised `variant` is `ERR_INVALID_REQUEST` reported before the path project id resolves; an empty value defaults to `PROVISIONAL` — `routes/projects.py:228-232`
- §3.8 — insert — ambiguity — `placed_in_service_date` may be any well-formed date, unconstrained relative to the clock date or the measuring period — `routes/projects.py:196,212`
- §4 — insert — ambiguity — trailing slashes address the same route; an undefined path/method returns the error envelope with `ERR_INVALID_REQUEST` under 404/405 rather than 400 — `app.py:16,42-51`

### Pass B — part applications, amendments, costs

94,651 -> **102,563 chars (+7,912)**, 423 lines unchanged; 17 change sites across 14 paragraphs (§3.3, §3.4 x5, §3.5 x4, §3.6 x5). Headings byte-identical to PRD_FINALIZED. No Pass A wording reverted. **ambiguity-pins: 12 · mismatch-revisions: 5.**

- §3.3 (submission) — revise — mismatch — the Part-1 exemption is narrowed to the `evaluation_status` precondition only; the `DISTRICT_NONCONTRIBUTING` bar is a separate check, tested **first**, and applies to every part number including Part 1 — `routes/part_applications.py:198-205`
- §3.4 (recommendation) — insert — ambiguity — acting caller must resolve in band 6 to an `ACTIVE` `SHPO` Reviewer (`ERR_UNAUTHORIZED`), while the `shpo_reviewer_id` comparison runs **after** the status check, so an unassigned reviewer on a non-`SHPO_REVIEW` row gets `ERR_PART_APPLICATION_INVALID_STATE` — `routes/part_applications.py:272-282`
- §3.4 (findings) — insert — ambiguity — finding creation resolves no Reviewer record at all (role header alone; no agency/credential check, no author recorded); the application's `version` increments for an `ADVISORY` finding too — `routes/part_applications.py:409-435`
- §3.4 (findings) — insert — ambiguity — a `VIOLATION` finding on a project past `NOT_MONITORED` re-scores every `ADMITTED` interest under `IN_SERVICE` and refreshes `max_investor_risk_score` (previously an entirely undocumented cascade trigger) — `routes/part_applications.py:437-440`
- §3.4 (determination) — insert — ambiguity — waived ids need not belong to the determined application (other applications' counters recomputed and `version` bumped); an already-`WAIVED` finding is inert; `review_note` validated then discarded — `routes/part_applications.py:305-377`
- §3.4 (determination) — insert — ambiguity — the `VIOLATION`-waiver refusal fires before branch selection, so it applies on `DENIED` too — `routes/part_applications.py:319-323`
- §3.4 (`APPROVED`) — insert — ambiguity — with both counters non-zero the violation is reported; the two checks follow the stated order, not §2.9's bands — `routes/part_applications.py:344-351`
- §3.4 (`APPROVED`) — insert — ambiguity — the hops are independently guarded: the property hop fires on any Part 1 approval whatever the property's status; the certification advance (and the Part 3 freeze-and-lock riding on it) fires only from the named origin state, else the project is untouched — `services.py:238-248`, `routes/part_applications.py:391-397`
- §3.4 (resubmission) — insert — ambiguity — no re-test of `listing_status`/`evaluation_status`/`placed_in_service_date`/certification dimension (resubmission works even on a `DECERTIFIED` project); findings and both counters carry over — `routes/part_applications.py:217-256`
- §3.5 (amendment draft) — insert — ambiguity — `part_application_id` need not belong to the named `project_id`; part number/status unexamined until submission; drafting mutates no other row — `routes/amendments.py:58-88`
- §3.5 (concurrence) — insert — ambiguity — the declared `X-User-Role` selects the branch and the reviewer record must match that agency and be `ACTIVE` (`ERR_UNAUTHORIZED`); `concurrence_note` discarded — `routes/amendments.py:191-198`
- §3.5 (resolution cascade) — revise — mismatch — "both require ..." reworded: the finding conditions gate the *cascade*, not the decision — the amendment still reaches `CONCURRED` with no error — `routes/amendments.py:134-144`
- §3.5 (resolution cascade) — revise — mismatch — second hop decrements whichever counter the severity feeds (not `unresolved_condition_count` unconditionally); third hop reworded to "both counters"; `version` bumps regardless — `routes/amendments.py:145-161`
- §3.5 (objection) — revise — ambiguity — the application is sent back only while the addressed finding is itself still `UNRESOLVED` — `routes/amendments.py:171-186`
- §3.6 (recording) — insert — ambiguity — `exclusion_reason` stays `NONE` even when created straight as `NON_QRE` and is not accepted from the client at creation; recording recomputes segregation/test/schedule and increments the project's `version` — `routes/costs.py:86-104`
- §3.6 (reclassification) — insert — ambiguity — a re-declaration of the classification already held is accepted and still counts — `routes/costs.py:143-150`
- §3.6 (reclassification) — revise — mismatch — derivation precedence pinned (supplied > `NONQUALIFIED_CATEGORY` > `OUTSIDE_MEASURING_PERIOD` > `NONE`); `DEVELOPER_FEE_CAP` and `REVIEWER_DISALLOWED` are **never** derived here; classification mutates only the item and the project — `routes/costs.py:41-48, 133-153`
- §3.6 (locking) — revise — mismatch — locking is a one-time hop (post-certification items open unlocked); a monitor's supplied `exclusion_reason` overrides `REVIEWER_DISALLOWED`; an already-`LOCKED_NON_QRE` item may be re-disallowed (count and both versions still move) — `routes/costs.py:121-150`
- §3.6 (system recapture trigger) — insert — mismatch — the trigger is the recomputation, not the actor: any classification on a `PART3_CERTIFIED` project that flips `MET -> NOT_MET` raises it, including a Developer's reclassification of a still-unlocked post-certification item — `routes/costs.py:51-59`
- §3.6 (qre-summary) — insert — ambiguity — every payload figure is computed under the requested variant (fee figures and `nonqualified_total_cents` shift too); threshold, classified total and in-period count do not — `calc.py:98-156`, `routes/projects.py:225-253`

**Pass A hand-off verdicts:** (1) `part_applications.py:198-204` ordering — CONFIRMED a real defect; PRD said flatly "Part 1 submissions are exempt" while impl refuses *any* part number on a `DISTRICT_NONCONTRIBUTING` property, before the `evaluation_status` test. Both facts pinned in §3.3. (2) `costs.py` `exclusion_reason` / version set — CONFIRMED and worse than expected: three defects (PRD's four-way derivation list implied the server derives `DEVELOPER_FEE_CAP` and `REVIEWER_DISALLOWED` — it never derives either; no precedence given for the category-vs-period overlap or the `NONE` case; a monitor-supplied `exclusion_reason` silently overrides `REVIEWER_DISALLOWED` on a locked item). Version set is exactly item + project (plus the failure cascade's rows), now stated.

### Pass C — investors, compliance, services, ledger + all deferred items

102,563 -> **108,376 chars (+5,813)**, 423 lines unchanged. **Whole of Step 9: 90,159 -> 108,376 chars (+18,217), 423 lines unchanged.** 22 pins across 17 paragraphs: **12 ambiguity-pins, 10 mismatch-revisions.**

- §2.5 — revise — mismatch — `recapture_pct` is no longer claimed to carry "exactly two decimal places"; both percentage fields are emitted as JSON numbers, so `25`/`25.00` echo as `25.0`, a full recapture reads `1.0`, a one-year step `0.2` — `services.py:298`, `routes/investors.py:118`
- §2.6 — revise — mismatch — the posture derivation is never run spontaneously or on a read, each hop fires only from the origin posture it names, and `COMPLIANT_CLOSED` is reached only via a covenant attestation measured against its `period_end_date` (deleted the false "single pass / never reads its own previous value" claim) — `compliance.py:83-95`, `services.py:335-354`
- §3.6 — revise — ambiguity — the Part 3 freeze covers `annual_credit_cents`/`total_claimable_credit_cents` alone; `credit_unclaimed_cents` keeps being re-derived — `services.py:119-127`
- §3.7 — insert — ambiguity — admission is the one `InvestorAdmin` write that resolves no acting interest, so no `ERR_INVESTOR_NOT_ADMITTED` arises there — `routes/investors.py:48-60`
- §3.7 — insert — ambiguity — the lessee slot is occupied by `kind` alone, so a `DISQUALIFIED` lessee does not free it — `routes/investors.py:34-38, 75`
- §3.7 — insert — ambiguity — band-10 order at admission: structure, then party tax status, then score — `routes/investors.py:62-104`
- §3.7 — insert — ambiguity — a `DIRECT_PARTNER`'s representation carries `lease_term_years` as null — `routes/investors.py:119`
- §3.7 — insert — ambiguity — an interest admitted onto an already-monitoring project is scored under `ADMISSION` and keeps that variant; `max_investor_risk_score` may mix variants — `routes/investors.py:102-124`, `services.py:177-187`
- §3.7 — insert — ambiguity — an `X-User-ID` resolving to no interest also yields `ERR_INVESTOR_NOT_ADMITTED` on the election — `auth.py:56-63`
- §3.8 — insert — ambiguity — covenant creation mutates no other row — `routes/compliance.py:64-80`
- §3.8 — insert — ambiguity — `SATISFIED` on an already-`COMPLIANT` covenant is `ERR_COVENANT_INVALID_STATE`, while `EXCEPTION` from it is accepted — `routes/compliance.py:115-133`
- §3.8 — revise — mismatch — breach cascade: interest `version` bumps only when score or `risk_variant_applied` changes; the posture hop fires only from `IN_SERVICE_MONITORING` yet the re-scoring still runs; project `version` conditional — `routes/compliance.py:155-159`, `services.py:166-174`
- §3.8 — revise — mismatch — cure: re-score first, then the posture return; project `version` increments only if either step changed something — `routes/compliance.py:160-166`
- §3.8 — insert — ambiguity — `RECAPTURED` is not a bar to further reported events (assessed, balance raised, dimension stays) — `routes/compliance.py:210-211`
- §3.8 — insert — ambiguity — `event_date` is never compared to the logical clock; the earlier-than-placed-in-service case is refused before any arithmetic — `routes/compliance.py:204-209`
- §3.8 — revise — mismatch — `OWNERSHIP_TRANSFER` hop stated as origin-guarded rather than a reportability precondition; the `CURE_PENDING` no-op-but-still-rescore case; the zero-amount case refreshes only `max_investor_risk_score`; `LEASE_TO_DISQUALIFIED` disqualifies before the re-score — `routes/compliance.py:215-226`
- §3.8 line 302 — revise — mismatch — trigger broadened to any cost recording/classification recomputation flipping `MET -> NOT_MET` on a `PART3_CERTIFIED` project; system event takes the clock date with no bounds check (negative `full_years_elapsed` possible); posture hop only from `IN_SERVICE_MONITORING` but fires whatever the amount, with `IN_SERVICE` re-scoring; `credit_unclaimed_cents` re-derived — `services.py:322-332`, `routes/costs.py:51-59`
- §3.9 — revise — mismatch — `claim_sequence` is computed once and never renumbered, so two claims can share one — `routes/investors.py:202`
- §3.9 — insert — ambiguity — opening a claim mutates no other row — `routes/investors.py:204-219`
- §3.9 — revise — mismatch — the acting-interest check precedes the creation state checks — `routes/investors.py:182-187`
- §3.9 — revise — mismatch — the standing-risk check precedes the pass-through-election check at filing; failing both reports `ERR_DISQUALIFICATION_RISK_TOO_HIGH` — `routes/investors.py:242-247`
- §3.9 — revise — mismatch — the acting-interest check precedes all filing state checks — `routes/investors.py:228-231`

**Deferred hand-off verdicts:**
- `apply_score` conditional version bump (§3.7/§3.8) — genuine exposure in `compliance.py`, fixed: §3.8 ¶292 and ¶294 now say only interests whose score or `risk_variant_applied` actually changes are mutated. §3.7 ¶278 (election) and ¶270 (admission) stay unconditional, which is correct — both `touch` unconditionally.
- `refresh_max_risk` never calling `touch(project)` — the only conditional caller is the covenant attestation (`project_changed` flag); `routes/investors.py` (admission, election), `routes/projects.py:216` (place-in-service) and `routes/compliance.py:228` (recapture event) all `touch(project)` unconditionally. Pinned exactly that way in ¶292/¶294; ¶270/¶278/¶284/¶300's unconditional wording left intact because it is accurate.
- `recapture_pct` / `credit_allocation_pct` as `float` — genuine mismatch; §2.5 revised with the concrete serialisations.
- `calc.recapture_assessment` negative-elapsed branch — `compliance.py:205` rejects `event_date < placed_in_service_date` for reported events, so the branch is unreachable there (pinned in ¶296). It **is** reachable through `substantial_failure_cascade`, which uses `clock.today()` against a future-dated `placed_in_service_date`; pinned in ¶302. (The branch is arithmetically identical to plain floor division, so "truncated downward" in ¶298 needed no change.)
- `substantial_failure_cascade` event date and missing bounds check — confirmed both; pinned in ¶302.
- §3.8 line 302 trigger clause too narrow — revised as above, cross-referencing §3.6's actor-neutral statement (Pass B's edit left untouched).
- `substantial_failure_cascade` interior — recapture row, `CURE_PENDING` hop (origin-guarded, amount-independent, with `IN_SERVICE` re-scoring), `FILED -> ADJUSTED`, and `refresh_unclaimed` all now in ¶302; ¶316's "net_claim_cents left unchanged" was already correct.
- `recompute_financials` calling `refresh_unclaimed` while frozen — confirmed; numerically unobservable (claimed/recaptured only move at filing, which refreshes too), so §3.6 ¶260 now scopes the freeze to the two schedule fields rather than claiming nothing is recomputed.

**Whole-document sanity check (Pass C) — PASS.** §4: 47 endpoint rows intact. §5: 46 `ERR_*` rows intact. Headings: title + §§1–5, §§2.1–2.11, §§3.1–3.9, plus the two `####` response-format headings — all present, in order, none lost or duplicated. File ends at a genuine boundary (the final §5 row, trailing newline); no mid-sentence truncation; 423 lines exactly as PRD_FINALIZED. No Pass A or Pass B edit reverted or contradicted. One pre-existing nit deliberately left alone: §3.9 ¶310 says filing is "gated on five things" while enumerating six — a doc-internal miscount, not an implementation mismatch.

### Orchestrator verification of Step 9

- `PRD.md` 423 lines / 90,012 chars · `PRD_FINALIZED.md` 423 / 90,159 · `PRD_COMPLETED.md` 423 / 108,376.
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` -> differs (the scan genuinely ran; 49 lines changed across the three passes).
- Structure re-checked independently: 46 `ERR_*` rows, 47 §4 method rows, 28 headings (identical count to `PRD.md`), last line is a complete §5 table row.
- `find` confirms **no** file under `workspace/implementation/`, `test_suite/` or `test_helpers/` is newer than `results.1.json` — Step 9 touched documentation only, so the Step 7 sweep result (8 rounds x 97/97) still holds for the artifacts on disk.

**PIPELINE COMPLETE.** Step 9 wrote `workspace/PRD_COMPLETED.md`.
