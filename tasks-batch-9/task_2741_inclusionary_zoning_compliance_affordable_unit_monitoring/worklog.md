# Worklog — task_2741_inclusionary_zoning_compliance_affordable_unit_monitoring

## Step 1: Create task directory — 2026-09-04T14:34:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2741_inclusionary_zoning_compliance_affordable_unit_monitoring` and its `workspace/` subdirectory. Index 2741 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed (other pipelines run concurrently on this host and auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-04T16:59:30.000Z

All three scaffold artifacts are complete and lint-clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2741_inclusionary_zoning_compliance_affordable_unit_monitoring/`):

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3659 | 195,416 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1197 | 121,804 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2823 | 392,640 |

`workspace/` and `worklog.md` were left untouched. No sibling task directory was read at any point.

**Contents**
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys): domain `inclusionary-zoning-compliance`, prefix `/iz-compliance`; 13 entities (flat topology), 15 state machines (cyclic), 21 calculations, 60 prioritised validations, 68 endpoints, 72 errors, 5 roles with segregation of duties, 2 OCC guards, `immediate` consistency; layers = dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): 9 rule blocks / 19 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): all nine claim-extraction-guide sections — entities 10, state_machines 10, calculations 14, validations 14, endpoints 6, errors 1, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1 = 65 instances, of which 10 are `excluded_because` stubs (5 calculations, 2 validations, 3 cross-cutting) that each cite an existing §1.8 instance by name.

**Verification performed**
- Instance names unique within §1.9 and disjoint from §1.8; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance; no stub carries a `test_recipe`.
- All 72 declared error ids are referenced by at least one design instance (the last stragglers — `ERR_MISSING_AUTH_HEADERS`, `ERR_UNKNOWN_ROLE`, `ERR_UNAUTHORIZED`, `ERR_NOT_RESOURCE_OWNER`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_STALE_PROJECT_VERSION`, `ERR_STALE_UNIT_VERSION` — are covered by the new errors, rbac and cross-cutting instances).
- Forbidden concurrency vocabulary swept out (one "simultaneously" in a rationale was rewritten); `created_at ASC` remains the only tie-break.
- Final lint verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  1242

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notable design points worth knowing downstream: OCC ordering is asserted in both directions (priority 8 beats the priority-9 project-state gate and the priority-22 enforcement gate, but loses to the priority-5/6 existence checks); the clock endpoint is a three-table sweep whose response is a count triple and is asserted idempotent on a second call; `record-restriction` freezes `ami_income_at_purchase_cents` against later AMI schedules; and the funder report's two bases are shown diverging on live state (ENTITLEMENT 10000 bps vs OCCUPANCY 5000 bps, dropping to 0 once a finding opens).

Orchestrator verification: all three files parse as YAML; `SCAFFOLD.yaml` contains neither design key; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` each have exactly one top-level key as required.

## Step 3: Copy shared files — 2026-09-04T17:00:10.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T17:18:00.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2741_inclusionary_zoning_compliance_affordable_unit_monitoring/workspace/PRD.md` — 659 lines, 120 KB, built incrementally (one `Write` + heredoc appends), ends cleanly at the last row of the §5 error table with no audit footer.

**Structure:** §1 Introduction; §2 Global Specifications with 11 domain-derived subsections (2.1 RBAC / 2.2 byte-verbatim response structure / 2.3 pagination and per-collection filters / 2.4 identity, timestamps, version and path resolution / 2.5 logical clock and the 4-step sweep / 2.6 cents, basis points and rounding / 2.7 ordinance and AMI vintages / 2.8 OCC on parent records / 2.9 the full 60-rung refusal ladder / 2.10 the two interval conventions / 2.11 the two conservation invariants); §3 Business Logic in 9 workflow subsections (baseline → screening/agreement → inventory → in-lieu pricing → marketing and lottery → certification and rent ceiling → monitoring/cure/enforcement → restriction, refinance, resale → trust fund, funder reporting, close-out); §4 endpoint table (4 columns, 68 rows); §5 error table (2 columns, 72 rows).

Hard Contract reports (transcript only, per the skill):

```
Field coverage check:
- entities[].fields: 151 required, 151 present, 0 missing (plus id/created_at/updated_at/version covered in §2.4)
- endpoints[].request_body: 74 required, 74 present, 0 missing
- endpoints[].query_params: 28 required, 28 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 60 checked, 60 expressed in prose (§2.9 normative ladder incl. both deliberate conflicts 19>43 and 22>39), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_project_version / expected_unit_version + ERR_STALE_PROJECT_VERSION / ERR_STALE_UNIT_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 77 checked across 15 machines, 77 fully expressed, 0 missing
- calculations[]: 21 checked, 21 fully expressed in prose incl. constants, pinned step order and precision, 0 missing
- validations[] conditions: 60 checked, 60 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 68 endpoints checked (36 carrying side effects), all expressed in §3 narrative, 0 missing
- entities[].fields[] structured content: 13 entities checked, all defaults/enums/ranges/initial values reconstructible, 0 missing
- sibling-branch symmetry: 23 groups checked (review APPROVE vs REQUEST_REVISION, submit-cure timely vs late, ROFR WAIVE vs EXERCISE, CLOSED vs CITY_PURCHASE_CLOSED, AMI_INDEXED vs SHARED_APPRECIATION, ENTITLEMENT vs OCCUPANCY, FULL/FRACTIONAL/SUBSTITUTION, the three OCCUPIED entries, etc.), 23 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1127
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional mechanical checks: all 72 scaffold error ids present with scaffold-matching statuses; §4's 68 method+path pairs and their role lists diff clean against the scaffold; all state enum values present; no fuzzy hedging words; the only code fences are the two inside the verbatim §2.2 block. Withheld design files were never opened, no sibling task dir was read, and `worklog.md` was not touched.

Orchestrator truncation guard (per the known doc-generator failure mode): `tail -25` shows the PRD terminating at the final row of the §5 error table — a real section boundary, not mid-sentence. Independently re-verified against SCAFFOLD.yaml: all 72 error ids and all 68 endpoint paths appear verbatim in PRD.md. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T18:20:00.000Z

The unit test suite for task 2741 is complete.

## What was produced

**`/home/ubuntu/github/CodingPRD/tasks/task_2741_inclusionary_zoning_compliance_affordable_unit_monitoring/test_helpers/`** (9 modules, 2459 lines)
`__init__.py` (135), `api_client.py` (510, one method per declared endpoint on a `GenericApiClient` subclass + module singleton), `api_errors.py` (169), `assertions.py` (173, incl. `round_half_up`/`apply_bps`, the three conservation assertions and `assert_fee_pricing_chain`), `constants.py` (115), `factories.py` (195), `fixtures.py` (631, tiered composites), `test_users.py` (58), `types.py` (473).

**`.../test_suite/`** (conftest.py + 11 test modules, 9336 lines, **177 tests**)
`conftest.py` (62) — `api` plus one fixture per role/auth-header variant.
Depth (queue A, 19 instances, 38 tests): `test_01_variant_and_formula_depth.py` (564/10), `test_02_state_machine_and_cascade_depth.py` (476/8), `test_03_priority_boundary_and_dependency_depth.py` (593/12), `test_04_temporal_and_invariant_depth.py` (473/8 — finished this session: certification closed-interval endpoint collision, marketing-window exact adjacency vs. enclosure, fund money conservation across request/disburse/void, withdraw–reinstate equivalents cycle).
Breadth (queue B, 55 instances, 139 tests): `test_05_entities.py` (664/17), `test_06_state_machines.py` (1244/33), `test_07_calculations.py` (984/9), `test_08_validation_guards.py` (1334/29), `test_09_closeout_resale_and_fund_guards.py` (973/12), `test_10_endpoint_behaviours.py` (850/13), `test_11_authz_occ_and_consistency.py` (1119/26).

## Audit results (all green)

- **Design-index coverage:** 84 instances in the two indices; 10 are `excluded_because` entries in the corner index that defer to a named difficulty instance, leaving 74 targetable. All 74 are covered, every queue-A instance by ≥2 tests. No instance was skipped for a PRD gap.
- **Tagging:** all 177 tests carry exactly one trailing `Design:` line, resolving to a real instance; zero untagged, zero dual-tagged, zero dangling tags.
- **Citations:** every test carries ≥1 `PRD: "…"` line and all quotes are byte-exact single-line substrings of `workspace/PRD.md` (0 failures out of the full set).
- `grep -rni scaffold` over both output dirs: no hits.
- `python3 -m compileall` clean; `pytest test_suite --collect-only -q` → **177 tests collected**, no import or fixture-resolution errors.
- Scope respected: nothing written under `workspace/` (it still holds only `INSTRUCTION.md` and `PRD.md`), `worklog.md` untouched, no sibling task read. `__pycache__` artifacts from the compile/collect checks were removed.

One design-vs-PRD conflict worth flagging upward: difficulty instance 11's narrative asserts `max_allowed_rent_cents == 143872` on an OWNERSHIP unit, but PRD §3.6 pins that field to 0 for ownership tenure, so that figure is deliberately not asserted; the test instead pins the error-ladder outcome (`ERR_UNIT_OUT_OF_COMPLIANCE`, 422), citing the general first-violated-rule sentence which uniquely derives it.

**Orchestrator note on step ordering (deviation + mitigation).** The skill requires Steps 5 and 6 to be launched concurrently in a single assistant message, partly for throughput and partly because concurrent launch gives the implementation generator *physical* isolation from `test_suite/` (the directory does not exist when impl-gen starts). I launched Step 5 alone by mistake, so by the time Step 6 was due, `test_helpers/` and `test_suite/` existed at the task root. Rather than accept degraded isolation and rely only on a prompt-level prohibition, I restored physical isolation before spawning Step 6: both directories were `mv`'d out of the project tree to `/tmp/task_2741_tests_hold/`, Step 6 ran with the task dir containing no test artifacts at all, and both directories were `mv`'d back to the task root immediately after Step 6 exited (verified present, 9 and 12 files respectively). Net effect on the artifact is nil — impl-gen provably could not read the tests — at the cost of the wall-clock overlap between the two steps.

Orchestrator verification: `test_helpers/` and `test_suite/` are at the TASK ROOT, not under `workspace/` (the known Step 5 misplacement failure mode did not occur); `workspace/` contained only `INSTRUCTION.md` and `PRD.md` at Step 5 exit.

## Step 6: Generate implementation — 2026-09-04T18:46:00.000Z

The implementation is complete, compiles, boots clean, and has been end-to-end smoke-tested.

## Location
`/home/ubuntu/github/CodingPRD/tasks/task_2741_inclusionary_zoning_compliance_affordable_unit_monitoring/workspace/implementation/`

## File inventory (3710 lines, 21 files)
| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 63 |
| `db.py` | 176 |
| `errors.py` | 186 |
| `middleware.py` | 276 |
| `response.py` | 57 |
| `services/calc.py` | 427 |
| `services/lookup.py` | 122 |
| `services/project_svc.py` | 115 |
| `services/sweep.py` | 77 |
| `services/fund.py` | 50 |
| `routes/certifications.py` | 450 |
| `routes/marketing.py` | 407 |
| `routes/resale.py` | 288 |
| `routes/fund.py` | 277 |
| `routes/projects.py` | 274 |
| `routes/units.py` | 266 |
| `routes/reference.py` | 188 |
| `routes/{__init__,services/__init__}.py` | 0 |

## Verification performed
- **`py_compile`**: `COMPILE_OK` on every `.py` file; `__pycache__` removed afterwards.
- **Boot**: `PORT=51743 bash start.sh` → ready in **0.66 s**, `/health` 200, and `GET /iz-compliance/projects` returns `total_count: 0` on a fresh process (proves nothing is seeded). Servers were killed by PID / by port only; no broad `pkill`.
- **Endpoint coverage (programmatic diff vs SCAFFOLD)**: all **68** declared method+path pairs present, **0 missing, 0 extra** (live map = 68 + `/health` + Flask `/static`).
- **RBAC (empirical, 68 × 5 roles = 340 probes)**: **0 mismatches** against every declared `roles:` list.
- **Errors**: all **72** declared error ids present with exactly the declared HTTP statuses.
- **Entity shape**: all **13** entities return exactly their declared fields + `id/created_at/updated_at/version` — no missing keys, no leaked internals (the hidden `_seq` / `_original_purchase_price_cents` keys are stripped by `db.public`).
- **List filters**: declared query params match `FILTER_FIELDS` for every collection endpoint.
- **Functional flows exercised live**: screening (47 units × 1500 bps → 7 units + 500 bps), PATCH-back-to-DRAFT re-screen with `screen_count`, agreement record + duplicate `doc_number`, unit creation/comparability refusal, marketing plan revision loop, half-open window adjacency accepted vs overlap rejected, lottery draw → RESERVED pairing, redraw rollback (and the correct `ERR_PLAN_NOT_APPROVED` afterwards, since `MarketingPlan.CLOSED` is terminal), certification cascades incl. `LotteryEvent → COMPLETED`, recert window + closed-interval period overlap, monitoring finding → cure → escalate → cure → cleared with segregation-of-duties refusals, penalty math (`3×overcharge + 25000`, 45-day deadline), withdraw → SUBSTITUTION fee → `ERR_SUBSTITUTION_FEE_PAID` on reinstate (oldest-fee-first selection), both `max_resale_price` variants, full resale chain to `CLOSED` and `CITY_PURCHASE_CLOSED` (occupant nulled, VACANT), ROFR auto-waive by sweep step 4, cert-expiry sweep step 2 and fee-delinquency step 3, trust-fund ledger conservation across request/disburse/void (`unencumbered` returns to the exact pre-request value), admin-cap refusal, both funder-report bases, close-out with agreement → RELEASED.

## Bug found and fixed during smoke-testing
`AffordableUnit.unit_number` is declared as a **string** (1..16 chars, unique per project, and the deterministic draw pairing key). The implementation was requiring an integer:
- `routes/units.py`: `take_int(payload,"unit_number",lo=1,hi=16)` → `take_str(..., min_len=1, max_len=16)`, and the rung-29 uniqueness check now compares strings.
- `routes/marketing.py`: draw pairing sort changed from `int(...)` to string ASC, matching "MARKETING units ordered by unit_number ASC".

Without this every unit creation would have returned `ERR_INVALID_REQUEST`, i.e. the whole suite would have collapsed.

## Constraints honoured
In-memory dicts only (no SQLite/disk/tmp); zero startup seeding; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` never read; no sibling task directory read; `worklog.md` untouched (mtime still 17:19); `find -newermt` confirms every file written lives under `workspace/implementation/`.

Orchestrator note: Step 6 ran with `test_helpers/` and `test_suite/` physically absent from the task directory (parked in `/tmp/task_2741_tests_hold/`), so the implementation could not have been fitted to the tests. Both directories were restored to the task root before Step 7.

## Step 7: Run tests and iterate to green — 2026-09-04T19:40:00.000Z

Green. Verified on disk: 8 complete `results.*.json`, every one `total=177 passed=177 failed=0 errors=0 skipped=0`.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps. Sweep #1: all 8 rounds identical at 160/177 (17 failures, zero flakiness — fully deterministic, so no load-induced noise to discount). Sweep #2 after the fix batch: all 8 rounds 177/177.

**Root-cause verdict: all 17 failures were test-layer defects. Zero implementation changes were needed** — `workspace/implementation/` is byte-for-byte as delivered (file mtimes 18:30–18:46, all predating this session).

### Tests deleted
None. No whole test was unfair enough to delete; four assertion-level removals under STEP 1c partial-coverage handling, each leaving every PRD-covered assertion in place:

| Assertion removed | Silence category | Rule that drove generation |
|---|---|---|
| `net_proceeds_cents is None` x4 pre-close (`test_10_endpoint_behaviours.py`) | COMPUTED-FIELD SILENCE — PRD defines `net_proceeds_cents` only at close ("Start from `net_proceeds_cents`, the `proposed_price_cents` minus the `broker_fee_cents`"), never its pre-close value | resale waterfall conservation |
| `penalty_final_cents == 0` (`test_01_variant_and_formula_depth.py`) | DEFAULT-VALUE SILENCE — §3.7 computes it only "at that instant" of cure submission; the PRD pins `cure_deadline` "stays null" and `penalty_at_base_cents` "stays 0" for the compliant branch but states nothing for `penalty_final_cents` pre-cure | `cure_extension_frozen_from_base_penalty_not_final_penalty` |
| `last_refinance_balance_cents is None` (`test_03`) → replaced with a before/after inertness + version-non-movement pair | DEFAULT-VALUE SILENCE (`test_helpers/types.py:264` declares it non-Optional `int`) | refinance ceiling boundary |
| `ami_income_at_purchase_cents is None` (`test_08`) → replaced with equality against the created unit's value + version-non-movement | DEFAULT-VALUE SILENCE | restriction-without-AMI-schedule guard |

The decisive counter-evidence for the `is None` family: `test_05_entities.py::test_unpriced_unit_money_fields_are_integer_zero` passes while asserting `== 0` on five unset `_cents` fields, so the suite itself contradicted the `None` sentinel.

### Fixes to `test_helpers/`
- **`assertions.py` → `assert_obligation_equivalents_conserved`**: scoped to `COMPLIANT_ONSITE`/`COMPLIANT_BY_FEE`. §2.11 states the invariant only "For a subject project that has reached a compliant posture", and §3.3 posture clause 4 defines `DEFICIENT` as exactly the case where the two legs sum to *strictly less* than the total — so the unguarded helper was asserting the opposite of the spec on 3 tests.

### Fixes to `test_suite/`
- **`test_02` x1, `test_04` x2**: `meta["total"]` → `meta["total_count"]`. §2.2/§2.3 declare `limit`, `offset`, `total_count`, `has_more`; there is no `total`. These raised `KeyError` and masked their own later assertions.
- **`test_03` → `build_out_of_compliance_ownership_unit`**: pass `reported_rent_cents=0`. The fixture was reporting 140000/month rent on an **OWNERSHIP** unit whose ceiling §3.6 fixes at 0 and whose `contract_rent_cents` §2.9/§3.6 require to be "exactly 0" — a PRD-inconsistent request. §3.7's `overcharge_monthly_cents` formula is unconditional, so the implementation's 140000 was faithful; the knock-on 445000 penalty bought a 15-day extension that pushed `cure_deadline` to 04-15 and made the 04-05 cure land *early*, yielding `CURE_SUBMITTED` where the builder's whole purpose was `ESCALATED`. With rent 0 the deadline is 2027-03-31 and both dependent tests pass unchanged.
- **`test_01` → `build_partly_occupied_rental_project`**: added `ctx["unit"] = fixtures.live_unit(...)`. The builder refreshed `ctx["project"]` but not `ctx["unit"]`, so the test asserted `OCCUPIED` against a snapshot taken before the certification that performs §3.6's `PLANNED → OCCUPIED` move.
- **`test_11` → `test_a_second_assessment_on_a_stale_project_version_writes_nothing`**: added the missing `fixtures.bootstrap_program()`. Every neighbouring test in the file calls it explicitly (no autouse fixture exists); without it a fresh per-test server has no ordinance, so setup died at `ERR_NO_GOVERNING_ORDINANCE`.

### Note for the orchestrator
I did not touch `worklog.md`. Two process notes worth keeping: (1) `sweep.log`-derived FAILED names were spliced garbage as warned — a name from one round attached to another round's failure, sending me after ~10 tests that passed individually; only `results.$i.json` is trustworthy. (2) `prd-bench-local-run` has no `--test-filter` flag, so I built a per-test-fresh-server pytest harness at `/tmp/fullrun2741.sh` driven by `API_BASE_URL`+`PORT` (~5.5 min for the full suite vs ~12 min for the 8-round sweep); it reproduced the sweep's failures faithfully in both directions. It needs its port-free precheck — an orphaned listener silently serves every test from one accumulating database and reports a catastrophic false 174/177.

**Orchestrator independent verification of the sweep artifacts** (the known "clean sweep with no results files" failure mode): `ls -la workspace/implementation/results.*.json` shows exactly 8 files, all mtime 19:37 (one sweep, not a mix of runs), each ~56 KB; parsing all 8 with `json.load` gives `total 177 passed 177 failed 0 errors 0 skipped 0` for every round. Green accepted.

**Step 8 gate:** NOT skipped. Step 7 made 0 `implementation/` fixes, but the skip condition is conjunctive and there were 4 assertion-level removals, 1 `test_helpers/` fix and 5 `test_suite/` fixes. The four removals are PRD silences by construction (COMPUTED-FIELD / DEFAULT-VALUE), which is exactly what Step 8 exists to pin.

## Step 8: Finalize PRD — 2026-09-04T19:50:00.000Z

`PRD_FINALIZED.md` is written at `.../workspace/PRD_FINALIZED.md`.

## Counts
- PRD.md: 660 lines / 119,928 chars. PRD_FINALIZED.md: 660 lines / 121,670 chars. Line count identical (all edits are in-paragraph); **+1.45% by characters**. Four lines touched: 281, 398, 412, 445.

## Changes (one bullet each)
- **§3.3 (unit creation defaults)** — insert — a fresh unit's six money attributes (`current_rent_cents`, `max_allowed_rent_cents`, `original_purchase_price_cents`, `ami_income_at_purchase_cents`, `last_refinance_balance_cents`, `approved_refinance_cap_cents`) begin at integer **0, not null**, and stay 0 (with `version` unmoved) through any refusal that never reaches the write — `implementation/services/project_svc.py:107-113`, `routes/units.py:198-207,258-265`.
- **§3.7 (review creation)** — insert — `penalty_final_cents` is **null** at creation and stays null on both the `COMPLIANT` and `FINDING_ISSUED` landings until a cure submission computes it; clear-cure and escalate never write it — `routes/certifications.py:283,351` (and :410-421, :440-450 which leave it alone).
- **§3.7 (`overcharge_monthly_cents` bullet)** — insert — the subtraction is **unconditional**: computed and stored on every review at creation, on the compliant landing too, and never consults `tenure`; an `OWNERSHIP` unit's ceiling is 0, so a non-zero reported rent becomes the whole overcharge and prices `penalty_at_base_cents`/the cure extension when any other finding fires — `routes/certifications.py:269,279,293-300`, `services/calc.py:339-348`, `routes/certifications.py:123-127` (OWNERSHIP `max_rent_cents` = 0).
- **§3.8 (resale submission)** — insert — the five proceeds-waterfall figures are integer **0 pre-close, not null**, and close is their only writer, so `SUBMITTED`/`PRICE_APPROVED`/`ROFR_WAIVED`/`ROFR_EXERCISED`/`BUYER_CERTIFIED`/`SUPERSEDED` all report 0 — `routes/resale.py:98-102,258-259`, `services/calc.py:309-333`.

No edit was made for four `<step_7_diff>` items that were pure test-layer bugs with PRD already determinative: the `assert_obligation_equivalents_conserved` scoping (§2.11 line 231 already limits the invariant to a compliant posture, §3.3 clause 4 defines `DEFICIENT` as the strict shortfall), `meta["total"]`→`total_count` (§2.2/§2.3 already declare only `total_count`), the `ctx["unit"]` staleness in `build_partly_occupied_rental_project` (§3.6 cascade 1 already pins `PLANNED → OCCUPIED`), and the missing `bootstrap_program()` in test_11.

## Per-edit pre-edit search log
1. **§3.3 unit money defaults.** (a) Subject: initial/unwritten values of a unit's `_cents` fields. (b) Enumerated: `services/project_svc.py:new_unit_row` (all six fields = 0; confirmed the six are the *complete* set of money fields on the row, so "every" is not overreach); writers of each — `routes/units.py:203-207` (restriction: `original_purchase_price_cents`, `ami_income_at_purchase_cents`), `:263-264` (refinance: cap + last balance), `routes/certifications.py:54-55,233-235` (cert/recert: `current_rent_cents`, `max_allowed_rent_cents`), `routes/certifications.py:364,379` (submit-cure: `current_rent_cents`), `routes/resale.py:266-269` (close: price basis + AMI anchor), `services/sweep.py` (expiry resets `current_rent_cents` to 0); refusal paths in `record_restriction` (`select_ami_schedule` raises before any write) and `refinance_review` (cap check raises before `db.touch`). (c) Adjustment: dropped a draft parenthetical listing "certification, deed restriction, refinance review, resale close" as the owning operations — it would have wrongly excluded submit-cure and the sweep expiry, both of which write `current_rent_cents`. Replaced with the looser "until some later operation writes it", and phrased the inertness clause as conditional ("refused *before it reaches that write*") so it cannot be read as a universal no-partial-write claim (`routes/units.py:124-134` does mutate a unit before a possible `ERR_NO_GOVERNING_ORDINANCE`).
2. **§3.7 `penalty_final_cents` null.** (a) Subject: lifecycle of `penalty_final_cents`. (b) Enumerated: grep for the field across `implementation/` → only `routes/certifications.py:283` (init `None`) and `:351` (submit-cure, on all three branches — timely, late/escalating, and re-entry from `ESCALATED`); read `clear_cure` (:389-421) and `escalate` (:424-450) to confirm neither touches it; `services/calc.py:358-369` for the value. (c) Adjustment: said "on either landing state" rather than scoping the null only to the compliant branch (the Step 7 site), since `FINDING_ISSUED` also carries null until a cure lands.
3. **§3.7 unconditional `overcharge_monthly_cents`.** (a) Subject: when/whether the overcharge subtraction runs, and for which tenures. (b) Enumerated: `routes/certifications.py:269` (computed before branch selection), `:279-280,291-300` (stored on both landings; `penalty_at_base_cents` stays 0 on the compliant landing), `services/calc.py:339-348`, `:375-393` (`RENT_OVERCHARGE` is the only `tenure`-gated part), consumers `calc.penalty_at_base`/`penalty_final`, and every writer of `max_allowed_rent_cents` to confirm an `OWNERSHIP` unit's ceiling is invariably 0 (`project_svc.py:108` default 0; `certifications.py:123-127` OWNERSHIP → `max_rent = 0`; recertify is unreachable for OWNERSHIP via rung 57 at `:203-205`; submit-cure writes only `current_rent_cents`). (c) Adjustment: initially wrote that the OWNERSHIP overcharge "prices the penalty", which would contradict the compliant landing where `penalty_at_base_cents` stays 0; re-scoped to "if any other finding does fire".
4. **§3.8 pre-close waterfall = 0.** (a) Subject: pre-close values of the five proceeds fields. (b) Enumerated: `routes/resale.py:98-102` (init 0), `:258-259` (close is the sole writer, via `calc.resale_waterfall`), `services/calc.py:309-333`, the intermediate transitions `approve_price` (:162-167), `rofr_decision` (:190-198), `certify_buyer` (:231-234) — none touch the five; supersession at `:112-117` (a `SUPERSEDED` row keeps its zeros); `services/fund.py:18-21` (`total_recapture_cents` sums `city_recapture_cents` over `CLOSED` only, so the pre-close zeros and the `CITY_PURCHASE_CLOSED` zero cannot leak into the ledger); `test_helpers/types.py:394` declares `net_proceeds_cents: int` non-Optional. (c) Adjustment: enumerated the specific non-closed states instead of writing "any state other than closed", so the sentence cannot be misread as covering `CITY_PURCHASE_CLOSED` (where `net_proceeds_cents` is non-zero and only `city_recapture_cents` is 0).

Orchestrator verification: `PRD_FINALIZED.md` exists, is NOT byte-identical to `PRD.md` (`cmp` differs), and the diff is exactly four in-paragraph edits at lines 281, 398, 412, 445 — no section added or dropped, tail still ends at the final error-table row. Measured sizes: PRD.md 659 lines / 120,361 bytes; PRD_FINALIZED.md 659 lines / 122,119 bytes (+1.46% bytes). The subagent's line/char figures differ trivially from mine (660 vs 659 lines, and its char counts) because it counted a trailing newline differently; the diff itself is what matters and it is exactly the four reported edits.

## Step 9: Complete PRD — 2026-09-04T21:05:00.000Z

`workspace/PRD_COMPLETED.md` written: 659 lines / 148,256 bytes, from `PRD_FINALIZED.md` (659 lines / 122,119 bytes) — **+26,137 bytes (+21.4%), 0 line delta** (every edit in-paragraph), 68 diff hunks, 74 individual edits: **58 ambiguity-pins, 16 mismatch-revisions**.

**Orchestrator decision — Step 9 run as three sequential route-partitioned passes.** The implementation is 3,699 lines across 19 modules with 68 endpoints; a single subagent doing an exhaustive impl-vs-PRD walk in one context would either run out of working memory or degrade into a sampling scan (the known failure mode: `PRD_COMPLETED.md` comes back byte-identical to its source, proving no scan happened). Partitioning by *route module* rather than by PRD section makes the passes' edit sets naturally disjoint while keeping coverage total, because every behavior surfaces through exactly one route module. All three passes share one output file, so they ran strictly sequentially: pass 1 owned Step 0's `cp` and passes 2 and 3 were explicitly forbidden from copying (a re-`cp` would have silently discarded the prior passes' work). Each pass was given the previous passes' hand-off notes so cross-partition gaps were routed to their owner rather than edited twice or missed.

- **Pass 1** — infra (`app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`) + `routes/reference.py`, `routes/projects.py`, `routes/units.py` + `services/{project_svc,lookup,sweep}.py`. 37 edits (29 ambiguity, 8 mismatch); 122,119 → 130,740 bytes. Pinned: the response envelope's `total_count`/`has_more` semantics, unbounded `offset` and past-end pages, empty-string-as-omitted param handling, the never-exposed insertion-sequence tie-break behind every `created_at ASC` rule, filter coercion and containment matching for unlisted/null/list params, `version` 1 with `updated_at` byte-identical to `created_at` on creation, host-wall-clock vs logical-clock field split, the clock's canonicalisation to 3 fractional digits and its lack of monotonicity, ordinance/AMI supersession only against *strictly earlier* ACTIVE rows (so out-of-order publication leaves two ACTIVE), rung-4 null-as-absent, several rung membership corrections (7, 9, 12), the §2.11 conserved sum being *at least* rather than exactly `total_obligation_bps`, and the withdrawal cascade's conditional posture movement. Excluded `GET /health` from the universal two-header rule.
- **Pass 2** — `routes/marketing.py`, `routes/certifications.py`. 18 edits (16 ambiguity, 2 mismatch); 130,740 → 140,743 bytes. Pinned: window instants canonicalised (vs Pass 1's verbatim `recorded_at`), `preference_categories`/`preference_claims` defaulting to `[]` and resubmit clearing them, a plan excluded from its own overlap scan, households not reader-scoped, `units_offered` never reconciled against inventory, **lexicographic** `unit_number` draw ordering (`10` before `9`) with pairing stopping at the shorter list, ladder precedence 27/30 over 55 on draw, the recert window opening at exactly midnight UTC 30 days before `expires_at` (inclusive), HTTP 201 on recert, `MARKETING`/`WITHDRAWN` units taking rent writes and a version bump with no occupancy move, and the conditional-vs-unconditional split across the cure fork/clear/escalate/re-entry cascades. Corrected the redraw prose: the plan stays `CLOSED`, so the documented "next draw re-ranks the pool" is unreachable (both a second draw and further applications fail rung 13).
- **Pass 3** — `routes/resale.py`, `routes/fund.py`, `services/fund.py` + the resale/fee/report parts of `services/calc.py`. 19 edits (13 ambiguity, 6 mismatch); 140,743 → 148,256 bytes. Pinned: the OCC 400-vs-412 boundary (a malformed token fails rung 4 before any comparison, so 412 requires a well-formed stale token), fee vintage read from the stored `ordinance_id` and never re-selected, `max_resale_price_cents` unfloored (a negative ceiling is frozen at submission and only surfaces at approval), the unfloored waterfall net and bucket 1, `original_purchase_price_cents` read at close rather than frozen at submission, ROFR exercise as a solvency test only with no ledger movement, only `SUBMITTED` siblings superseded (two live transactions can coexist), and the close-time retirement scan retiring every `CERTIFIED` cert when the seller household is null. Corrected four mismatches including the funder report's "SUPERSEDED excluded from every metric" (superseded payments do still count in `total_fees_paid_cents`, so paid can exceed assessed) and the prior-link rule ("immediately preceding" → any `CLOSED` resale of the unit).

Three of Pass 3's seven handed-down leads correctly produced **no** edit after source verification, which is the right outcome: the zero-`ami_income_at_purchase_cents` fallback, the missing-size-key `ERR_NO_AMI_SCHEDULE` path, and the missing-`fee_gap_level_bps` path are all unreachable through the API (publication-time validation forecloses them), and documenting an unreachable state would have added PRD prose describing behavior the implementation cannot exhibit.

**Orchestrator verification of the final artifact:**
- `PRD_COMPLETED.md` is NOT byte-identical to either `PRD_FINALIZED.md` or `PRD.md` (`cmp` differs against both) — the known "scan never ran" failure mode did not occur.
- Structure intact: still 659 lines, identical `^#` heading count to `PRD_FINALIZED.md`, all 72 error rows present, tail still ends at `| ERR_FEE_OUTSTANDING | 409 |` (a real section boundary, not a truncation).
- `find -newermt` confirms **no** file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` was modified after the 19:37 green sweep, so Steps 8 and 9 were documentation-only and the verified 8×177/177 result still describes the shipped artifact.
- `__pycache__` directories removed; the task tree contains exactly the artifacts the skill's Output section specifies.

**PIPELINE COMPLETE.** Steps 1–9 all finished. Final state: 177 tests, 8/8 sweep rounds at 177/177, 0 implementation defects found in Step 7, and a PRD lineage of PRD.md → PRD_FINALIZED.md (4 edits) → PRD_COMPLETED.md (74 further edits).
