# Worklog — task_2515_correctional_food_service_operations

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2515_correctional_food_service_operations` and its `workspace/` subdirectory. Index 2515 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T05:29:00.000Z

All three artifacts are complete, parse as valid YAML, and the scaffold linter reports a clean verdict.

```
Coverage
  §1.5 endpoints declared:    77
  §1.1 entities declared:     16
  §1.8 instances scanned:     18
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  881

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2515_correctional_food_service_operations/`):
- `SCAFFOLD.yaml` — 3,526 lines; §1.0–§1.7 only, neither design key present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,030 lines; single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4,028 lines; single key `scaffold_corner_design`.

§1.0–§1.7 shape: prefix `/cfs`, 16 entities, 13 state machines (2 of them the parallel `production_stage` / `qa_status` axes of ProductionBatch), 3 §1.2.1 concurrency rules, 14 calculations, 50 ordered validations, 77 endpoints, 72 errors, 8 roles. Profile: `compliance_audit` + `posture_driven_gating`, graph topology, parallel state-machine shape, segregation-of-duties role model, immediate consistency, layers `[cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency, derived_field_reconciliation]`.

§1.8 — 9 rules x 2 = 18 instances: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

§1.9 — 80 instances (56 with full recipes, 24 `excluded_because` stubs), all 9 guide sections: entities 12 (10/2), state_machines 17 (9/8), calculations 11 (4/7), validations 8 (5/3), endpoints 5 (4/1), errors 13 (13/0), rbac 5 (5/0), cross_cutting_complexity_layers 7 (5/2), consistency_model 2 (1/1). Names are globally unique across both design files, every stub's cited `difficulty_instance` resolves, and no stub carries a `test_recipe`.

Design adjudications worth flagging:
- **Unreachable error found and fixed in `SCAFFOLD.yaml`.** `ERR_SHARPS_DISCREPANCY_OPEN` (priority 20) could never fire: any `UNACCOUNTED` tool forces `kitchen_posture` to LOCKDOWN (sharp) or RESTRICTED (non-sharp) via posture clauses 1/5, so the priority-19 posture gate on `POST /cfs/tool-issuances` always pre-empted it. I added a carve-out to priority 19 — on that endpoint only, the posture gate is evaluated against posture clauses 2/3/4 and defers the UNACCOUNTED clauses to priority 20 — and updated the error catalog condition. Priority numbers were left untouched so existing §1.8/§1.9 citations of `priority=19` stay valid; the new `corner_tool_issue_eligibility_ladder_rejects_each_way` instance asserts the carve-out explicitly.
- Enum drift caught by a systematic sweep of every `field: "VALUE"` pair in both design files against §1.1: `STANDING_COUNT` → `FORMAL_COUNT` (14 sites), `SHARP_IMPLEMENT` → `SHARP`, `TRAY_LINE` → `SERVING_LINE`, `KNIFE`/`shadow_board_slot: "A1"` → `SHARP_KNIFE`/integer slot, and a grounds reference to a non-existent calculation name → `special_diet_census_invariant`.
- Pagination metadata lives in `meta`, not `data`, so the `ERR_VALUE_OUT_OF_RANGE` instance asserts `meta.total_count` / `meta.has_more` in prose instead of capturing them (the linter correctly rejected `$.data.total_count` against a list output).
- `GET /cfs/diet-orders/{id}` deliberately excludes `ContractAdministrator`; the `shared_operations` instance turns that into a claim (senior role is 403 on the individual order but reads the facility's `active_special_diet_count`).
- 61 of the 72 catalogued errors are named in the design files. The remaining 11 (`ERR_COOK_CHILL_NONCOMPLIANT`, `ERR_COST_CEILING_EXCEEDED`, `ERR_DUPLICATE_SERVICE_RECORD`, `ERR_FORECAST_DATE_PAST`, `ERR_INMATE_NOT_IN_CUSTODY`, `ERR_LD_VARIANT_REQUIRED`, `ERR_NO_ACTIVE_MENU_CYCLE`, `ERR_OPEN_BATCHES_REMAIN`, `ERR_REHEAT_LOG_MISSING`, `ERR_SERVICE_WINDOW_MISMATCH`, `ERR_SUBSTITUTION_NOT_EQUIVALENT`) each have a single-rule trigger path in §1.4 and are left for exhaustive enumeration at PRD/test-suite generation time rather than duplicated as §1.9 corners.
- Every assert literal is pre-computed from the declared formulas (e.g. 2800 kcal / 58.50 g protein / 2000 mg sodium / 315 c per meal-day on the canonical 3-item cycle; forecast 14 line + 8 waste = 22; 153-of-156 served → 0 missed at tolerance 3, 51 meal-days, score 100.00; grievance due dates 2026-08-06 / 2026-08-11 / 2026-08-08).

No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-03T05:29:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T05:48:00.000Z

PRD generation is complete.

**Output:** `workspace/PRD.md` — **616 lines**, written incrementally (one `Write` + nine `cat >>` heredoc appends with sentinel `PRD_CHUNK_EOF`). The file ends at a real boundary: the last row of the §5 error table (`| ERR_COST_CEILING_EXCEEDED | 422 |`). No audit footer, no contract reports in the file.

**Structure:** §1 Introduction → §2 (2.1 RBAC, 2.2 verbatim response structure, 2.3 Pagination, 2.4 Resource Identity/Audit Stamps/Logical Clock, 2.5 The Rejection Ladder, 2.6 Stale-Version Guards, 2.7 Arithmetic/Rounding/Units, 2.8 Segregation of Duties, 2.9 Kitchen Posture, 2.10 Cascade Discipline) → §3 (9 subsections: contract+facilities, menu cycle, roster/diet orders, counts+forecasts, cook-chill/HACCP/QA, labour/tools/contraband, service records/substitutions, grievances, reconciliation/close) → §4 endpoint table → §5 error table.

**Isolation constraint honoured:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced. Only `SCAFFOLD.yaml`, `SKILL.md`, and `section-2.2-response-structure.md` were read.

**Coverage confirmation (all mechanically verified with python/yaml against SCAFFOLD.yaml):**
- **77 / 77 endpoints** — all present in the §4 table (77 data rows), and every one also has a §3 prose representation (including the clock setter, both computed summary views, and all three sub-resource listings with their filters).
- **72 / 72 errors** — all present in the §5 table (72 data rows), and every single error ID also appears in §2/§3 prose *before* §4, so no error reaches the reader as a bare table row.
- **50 / 50 validations** — the full priority ladder is in §2.5 (priorities 1–18 enumerated, 19–50 as an ordered prose sentence), with each condition restated next to the workflow it guards in §3, including the priority-19/20 tool-issuance posture carve-out.
- **14 / 14 calculations** — nutrition adequacy (per-item rounding first, forbidden alternative named), cost per meal-day (satellite tiers, single terminal ceiling), forecast trays (0.94 participation, 1.03 transport loss, three waste tiers), temperature in-range (all six log points, inclusive limits), cook-chill compliance (existence not universality), chiller occupancy (closed intervals), diet coverage window (half-open), sharps reconciliation (conservation identity), kitchen posture (6-clause waterfall), missed meals (floor tolerance, weight 3), liquidated damages (normative 9 steps, both variants, cap-before-credit with the forbidden-order numbers), substitution equivalence (three inclusive bands), grievance SLA (5/10-day windows, inclusive deadline), special-diet census invariant.

**Hard Contract reports:**
- **Contract 1 (Field-Name Coverage): PASS** — 208 required identifiers (184 entity field names + id/created_at/updated_at/version + 20 endpoint-only input/query identifiers); 0 missing. Two gaps found and fixed during verification: `production_batch_id` (added to the §3.5 temperature-log paragraph) and the menu-cycle listing filters (`facility_id`, `status` added to §3.2).
- **Contract 2 (Rule Coverage): PASS** — all six high-risk categories surfaced: validation priority ordering (§2.5), all three OCC stale-version rules with expected_inmate_version/expected_facility_version/expected_service_contract_version and their 412 error IDs (§2.6), every cascade hop chain including the 4-hop unaccounted-tool chain with its NON_SHARP divergence and the fan-out incident, all applies_to scopes, all field-level defaults/structured content, and all sibling-branch symmetry pairs (SANCTIONED vs CLEARED, APPROVED vs REJECTED, CLOSED vs RESPONDED vs ESCALATED, COUNT_DRIVEN vs ROSTER_DRIVEN, INCIDENT_BASED vs POPULATION_WEIGHTED, single-branch vs dual-track join).
- **Contract 3 (§3 Path Purity): PASS** — 0 violations; no backticked token in §3 starts with `/`, is a bare HTTP method, or combines method+path.

Also scanned clean: no pseudocode operators anywhere in §2 or §3, and no numeric hedging language.

**Orchestrator truncation check:** `wc -l` = 616; `tail -25` confirms the file ends at the final §5 error-table row, a real section boundary. Not truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T06:20:00.000Z

Implementation complete and verified.

## Files written (all under `workspace/implementation/`)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | installs flask only if missing, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 60 | `create_app()`, 8 blueprints, `strict_slashes=False`, ApiError/HTTPException/catch-all handlers, `PORT` env |
| `core.py` | 554 | roles, all 72 error ids -> (status, message), logical + wall clock, `iso()` 3-digit, in-memory `DB` (16 dict collections), row helpers, envelope/pagination, `validate_fields` three-sweep validator |
| `calc.py` | 719 | all 14 calculations + every PRD constant, posture waterfall, derived-counter refreshers, ledger apply/reconcile, forecast variants, equivalence bands, cook-chill anchors |
| `ops.py` | 291 | 15 `need_*` lookups, terminal/state guards, cascade hops (lockdown discard, unassign, system incident, escalations, close-out verdict, reconciliation invalidation), computed views |
| `routes_contract.py` | 290 | 15 endpoints (clock, contract, facility, sharps audit/summary) |
| `routes_menu.py` | 210 | 9 endpoints |
| `routes_roster.py` | 325 | 11 endpoints |
| `routes_forecast.py` | 168 | 7 endpoints |
| `routes_batch.py` | 283 | 7 endpoints |
| `routes_security.py` | 360 | 13 endpoints |
| `routes_service.py` | 268 | 9 endpoints |
| `routes_grievance.py` | 239 | 6 endpoints |
| **total** | **3778** | |

**Endpoints: 77** registered `/cfs` method+path pairs, exactly matching the scaffold's 77.

## Verification performed
- `python3 -m py_compile` clean on all 12 modules; `__pycache__` removed.
- Storage audit: zero hits for `sqlite`, `open(`, `json.dump`, `pickle`, `shelve`, `/tmp`. Pure in-memory dicts, empty at every boot, no seeding anywhere.
- Booted on `PORT=18517` and ran three probe scripts covering: full happy path (contract -> facility -> cycle -> items -> sign -> activate -> inmate -> diet order -> verify -> count -> forecast -> lock -> batch -> 3 temperature logs -> 4 stage advances -> QA pass -> service record -> close -> substitution -> approve -> grievance DUAL_TRACK -> both branches -> respond with MEAL_REFEED -> reconcile -> performance-summary -> close), the sharps/lockdown chain (audit shortfall -> LOCKDOWN -> clean audit -> OPEN -> declare-unaccounted -> batch discard + line-worker unassign -> recovery return), the full diet-order reverification cycle to the bound-2 ceiling, and ~25 negative ladder probes. All produced the PRD-specified error ids, statuses and computed values (e.g. forecast 109/8/117, `meal_days_served` 36, LD 2000, cost-recovery 400, net 1600, cycle cost 1224 vs ceiling 900 -> `ERR_COST_CEILING_EXCEEDED`). Server killed; port confirmed closed.

Four probe results initially looked like mismatches; all four turned out to be wrong expectations in the probe, confirmed against the PRD/scaffold: sharps-audit rejects `counted + issued + unaccounted > authorized` (§3.6 line 331), `suspend` is FoodServiceSupervisor/CorrectionalOfficer only, an unknown role is 401 `ERR_UNKNOWN_ROLE` vs 403 `ERR_UNAUTHORIZED` for a known-but-unlisted role, and `ERR_VERIFIER_ROLE_MISMATCH` is 403. No implementation changes were needed.

## PRD ambiguities resolved (choice named)
- **nutrition-sign order**: `ERR_MENU_CYCLE_INCOMPLETE` fires *before* the nutrition/sodium gates (§3.2 prose beats scaffold priority 43 > 29/30). No contract-active gate on sign.
- **Everywhere else the §2.5 ladder beats §3 prose order**: SoD(27) before `ERR_CONTRACT_NOT_ACTIVE`(43) on cycle activate; window-mismatch(41) before forecast-not-locked(42) on record create; custody(28) before `ERR_INVALID_WINDOW`(37) on diet-order create; clinical-indication(25) before verifier-role(26) on verify; forecast-date-past(41) before no-active-cycle(42) on lock; chiller(40) before forecast-not-locked(42) on batch create; log-sequence(33) before batch-discarded(34); reconcile's two `ERR_INVALID_STATE` preconditions(17) before `ERR_LD_VARIANT_REQUIRED`(48).
- **Undeclared-error cases mapped to priority 5/6**: `clinical_indication` supplied on a RELIGIOUS order -> `ERR_INVALID_REQUEST`; a diet code from the wrong family -> `ERR_INVALID_ENUM_VALUE`; `produced_trays` missing when advancing to COOKED -> `ERR_INVALID_REQUEST` (<=0 -> `ERR_VALUE_OUT_OF_RANGE`); `returned_count_verified` absent or != 1 -> `ERR_INVALID_REQUEST`; `sanction_type` missing on SANCTIONED / present on CLEARED -> `ERR_INVALID_REQUEST`. `ld_variant` is deliberately *not* validated at 5/6 — it surfaces as `ERR_LD_VARIANT_REQUIRED` at 48.
- **`open_sharps_discrepancy_count = sharps_unaccounted_count + sharps_audit_shortfall`** (§3.6 wins over the scaffold formula).
- **Kitchen-posture carve-out on tool issue**: `derive_posture(skip_unaccounted_clauses=True)` for the priority-19 gate so the unaccounted clauses report as `ERR_SHARPS_DISCREPANCY_OPEN` one priority later.
- **Worker gates diverge by endpoint**: assign to BARRED -> `ERR_ALREADY_TERMINAL`, already ASSIGNED -> `ERR_INVALID_STATE` (before the posture gate); tool issue to SUSPENDED *or* BARRED -> `ERR_WORKER_NOT_CLEARED` (no terminal check there), per §3.6's explicit wording.
- **`ERR_ILLEGAL_TRANSITION` is effectively advance-stage-only**; qa-decision origins come from a `QA_ORIGINS` map and anything else is `ERR_INVALID_STATE`(17).
- **Temperature-log posting bumps the batch iff a persisted batch field net-changed** (the log itself is immutable — no version, no `updated_at`).
- **PATCH meal-service-record**: DISPUTED -> `ERR_ALREADY_TERMINAL`, CLOSED -> `ERR_INVALID_STATE`. **Grievance respond** from any non-READY, non-terminal state -> `ERR_BRANCHES_INCOMPLETE`, never `ERR_INVALID_STATE`. Grievance route link preconditions -> `ERR_INVALID_STATE`. DUAL_TRACK sets `status="DUAL_TRACK"` but `routed_branch="BOTH"`.
- **DIET_REINSTATEMENT clears only `verified_by_user_id` and `verified_at`** (§3.8 literal), unlike §3.3 reverification which also clears `verification_expires_at` and `suspension_reason`.
- **Substitution approved on a RECONCILING contract**: hop 1 recomputes `substitution_rate_pct`, hop 2 then zeroes it via invalidation — one net version bump.
- **Inmate movement has no terminal/state gate** (a RELEASED inmate may be moved again); `housing_unit` omitted on HOUSING_CHANGE is a silent no-op.
- **A menu item may be added to an ACTIVE cycle**; only NUTRITION_APPROVED reverts to DRAFT (clearing the four `approved_*` fields plus the signer); RETIRED -> `ERR_ALREADY_TERMINAL`. Both `cycle_day` bounds report `ERR_CYCLE_DAY_OUT_OF_RANGE`.
- **No `ERR_FORECAST_DATE_PAST` on service-record create** (lock only), and **no facility-mismatch check between a forecast and its population count**.
- **`created_at`/`updated_at`/`api_request_timestamp` use the wall clock**; every domain `*_at` uses the logical clock; `service_date` is echoed exactly as supplied.

## Step 5: Generate unit tests — 2026-09-03T07:05:00.000Z

Suite complete and verified.

## Files written

`test_helpers/` (Stage 1 infrastructure, 2,623 lines):
| file | lines |
|---|---|
| `test_helpers/__init__.py` | 65 |
| `test_helpers/api_client.py` | 610 |
| `test_helpers/api_errors.py` | 213 |
| `test_helpers/assertions.py` | 409 |
| `test_helpers/constants.py` | 82 |
| `test_helpers/factories.py` | 396 |
| `test_helpers/fixtures.py` | 381 |
| `test_helpers/test_users.py` | 73 |
| `test_helpers/types.py` | 394 |

`test_suite/` (Stage 2, 6,308 lines, 92 tests):
| file | lines | tests |
|---|---|---|
| `conftest.py` | 20 | — |
| `test_a01_dual_variant_calculations.py` | 334 | 5 |
| `test_a02_combinatorial_formulas.py` | 254 | 4 |
| `test_a03_state_machine_loops.py` | 314 | 4 |
| `test_a04_transitive_cascades.py` | 301 | 4 |
| `test_a05_validation_precedence.py` | 277 | 4 |
| `test_a06_boundary_precision.py` | 247 | 4 |
| `test_a07_cross_entity_state.py` | 242 | 4 |
| `test_a08_temporal_overlap.py` | 321 | 4 |
| `test_a09_compensating_invariants.py` | 360 | 4 |
| `test_b01_entities.py` | 463 | 10 |
| `test_b02_state_machines.py` | 496 | 8 |
| `test_b03_calculations.py` | 374 | 4 |
| `test_b04_validations.py` | 313 | 5 |
| `test_b05_endpoints.py` | 286 | 4 |
| `test_b06_errors.py` | 915 | 13 |
| `test_b07_rbac.py` | 287 | 5 |
| `test_b08_cross_cutting.py` | 504 | 6 |

## Tests per queue
- **Queue A (Difficulty)** — 37 tests covering **18 of 18** instances, every instance with >=2 tests as §2.1 requires.
- **Queue B (Corner)** — 55 tests covering **55 of 56** non-stub instances, one test each.

Machine-verified: 92 test functions, 92 `Design:` tags, every test exactly one tag (no untagged, no dual-tagged), every tag resolves to a real `name:` in its source yaml, every docstring cites the PRD.

## Skipped
- **`Corner/state_machines/corner_menu_cycle_reverts_to_draft_when_an_item_is_added` — non-unique-derivability.** The revert is unreachable under the PRD: signing requires `item_count == cycle_length_days x 3` *exactly*, the `(cycle, cycle_day, meal_slot)` triple is unique, and `ERR_CYCLE_DAY_OUT_OF_RANGE` bars new days — so every further add to a `NUTRITION_APPROVED` cycle is `ERR_DUPLICATE_RESOURCE` and the transition can never fire.
- **The 24 `excluded_because:` stub instances were intentionally not translated** per `SKILL.md` ("skip the stub, do not emit a placeholder test"); the cited queue-A difficulty instance owns each assertion. 21 tests from an earlier pass that had been wrongly tagged to stubs were found and deleted — each duplicated a queue-A test already emitted in `test_a01`–`test_a09`, so no claim coverage was lost. Unused imports left behind by the deletions were pruned (pyflakes clean).

## Notable adjudication
`corner_occ_diet_order_create_rejects_stale_inmate_version`'s recipe asserts `active_diet_order_count == 1` after a `PENDING_VERIFICATION` create. The PRD contradicts it twice (line 230: "`active_diet_order_count` does not move until verification"; line 238 excludes `PENDING_VERIFICATION`). The PRD-derived `0` was asserted, since the PRD is the contract under test.

`pytest --collect-only` collects all 92 with no errors; `py_compile` passes on all 27 generated `.py` files. `workspace/implementation/` was never read or written.

**Orchestrator note:** independently confirmed `python3 -m pytest test_suite/ --collect-only -q` -> "92 tests collected", zero collection errors. `test_b09_consistency.py` existed transiently mid-generation and was removed in the stub-tag cleanup described above; the 17 surviving test files match the table exactly.

## Step 7: Run tests and iterate — 2026-09-03T07:52:00.000Z

All 8 parallel rounds pass 92/92. Exiting.

## Summary

**Iterations run:** 2 (initial sweep found 4 deterministic failures reproducing in all 8 rounds; second sweep after fixes was clean 8/8 at 92/92).

**Tests deleted:** none. Two assertions were removed under STEP 1c partial-coverage handling (see below); no whole test was dropped, and no assertion was weakened or skipped.

**Fixes applied to `test_helpers/`:** none. The failures were not a shared upstream fixture bug — each traced to a per-test assertion or per-test setup.

**Fixes applied to `test_suite/`:**

- `test_suite/test_b01_entities.py`, `test_a_new_contract_lands_in_draft_with_every_ledger_figure_at_zero` and `test_a_new_menu_cycle_generates_its_system_fields_and_leaves_approvals_null` — removed the four `assert_instant(created_at/updated_at, "2026-08-01T00:00:00Z")` lines (**source-of-value silence**, STEP 1b/1c). PRD §2.4 enumerates the logical-clock-sourced fields as a closed em-dash list of 20 named `*_at` fields that conspicuously excludes `created_at` and `updated_at`, both of which are introduced in the two preceding paragraphs with no clock reference. Decisively, the PRD elsewhere uses `created_at` as the tiebreaker *for* logical-clock fields — "where two arrivals share an instant the one with the earliest `created_at` wins", "Ties on `logged_at` are broken by earliest `created_at`", and §2.3's "ordered by `created_at` ascending … stable across pages" — all of which are non-functional if `created_at` is frozen to the logical clock. A faithful PRD-only reader stamping `created_at` from the host clock (as the implementation does) is correct, so the assertion was not uniquely derivable. The rest of both tests (defaults, zeroed ledger, UUID shape, `version == 1`, echoed inputs) was kept intact.

- `test_suite/test_b08_cross_cutting.py`, `test_a_clean_sharps_audit_invalidates_a_batch_token_without_changing_the_posture` — the trailing assertion expected the facility `version` to stay at 2 after a successful batch create, with the comment "the batch is a child row, not a facility mutation". This contradicts PRD §3.5 verbatim: a created batch "also increments the facility's `version` by 1, because the facility's chiller occupancy has changed." Corrected the expectation to 3 (STEP 2, assertion mis-translated PRD; the fix makes the test *more* faithful).

- `test_suite/test_b06_errors.py`, `test_each_way_a_worker_can_fail_the_sharps_gate_has_its_own_code` — test-setup bug (STEP 2). The test left worker C's `OPEN` contraband incident standing, then declared a `NON_SHARP` tool unaccounted, which per §3.6 auto-raises a second `OPEN` incident at the same facility. With `open_contraband_incident_count == 2`, posture clause 4 fires — and clause 4 *is* inside the tool-issue carve-out set (clauses 2, 3, 4) — so the implementation correctly returned `ERR_KITCHEN_POSTURE_BLOCKED` rather than the `ERR_SHARPS_DISCREPANCY_OPEN` the test wanted. Added a `CLEARED` disposition of worker C's incident (by `OFFICER_2`, satisfying §2.8) before the declaration, so only clause 5 holds and the carve-out under test is actually isolated. The assertion itself was left exactly as written.

**Fixes applied to `implementation/`:** none. All four failures were test-side; in particular the `ERR_KITCHEN_POSTURE_BLOCKED` result and the facility version bump on batch create were both the PRD-required behaviour, and no PRD-required check was relaxed to accommodate a fixture.

**Orchestrator verification:** independently parsed all 8 `results.$i.json` — every round reports `passed == total == 92`.

**Orchestrator adjudication on the Step 8 skip condition:** Step 8 is NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 made 3 `test_suite/` fixes, two of which (the removed `created_at`/`updated_at` clock-source assertions) are exactly the PRD-silence signal Step 8 exists to pin. Proceeding to Step 8.

## Step 8: Finalize PRD — 2026-09-03T08:00:00.000Z

Done. `PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 616 lines
- `PRD_FINALIZED.md`: 616 lines
- Line-count delta: 0 (0.00%). One line revised in place (line 93); character delta +489 (~0.36% of the 134 KB document).

## Changes
- **§2.4 (Resource Identity, Audit Stamps and the Logical Clock)** — *revise* — appended two sentences to the logical-clock paragraph pinning `created_at` and `updated_at` as host-wall-clock stamps, explicitly outside the closed em-dash list of 20 logical-clock-sourced `*_at` fields, and unaffected by clock repositioning — `implementation/core.py:168-170` (`now_wall`), `core.py:274-281` (`base_row`), `core.py:284-289` (`touch`).

No other edit. The remaining two `<step_7_diff>` items are pure test-side bugs against prose the PRD already states verbatim, so their wording was kept byte-identical:
- Facility `version` bump on batch create is already stated in §3.5 line 272 ("also increments the facility's `version` by 1, because the facility's chiller occupancy has changed") and `routes_batch.py:107` does exactly that via `sync_facility(..., force=True)`.
- The tool-issue posture carve-out over clauses 2/3/4 and the auto-raised `OPEN` incident on an unaccounted declaration are already pinned by §2.9 line 166, §3.6 line 314 and §3.6 line 327; `routes_security.py:144-147` (`derive_posture(..., skip_unaccounted_clauses=True)` then `unaccounted_any_present`) and `routes_security.py:237` (`raise_system_incident`) match them.

## Per-edit pre-edit search log

**Edit 1 — §2.4 `created_at`/`updated_at` source of value**

(a) **Subject identified:** where the values of `created_at` and `updated_at` come from, and every downstream behavior that reads them.

(b) **Impl paths enumerated (read/grepped):**
- `core.py:168-170` — `now_wall()` returns `datetime.now(timezone.utc)`; docstring names it as the source for `created_at`/`updated_at` and envelope meta.
- `core.py:274-281` — `base_row()`: the *single* creation path. Stamps `created_at` (and `updated_at` when `with_version=True`) from `now_wall()`. Grep confirmed it is the only writer of `created_at`; every POST route funnels through it: `routes_contract.py:76,212`, `routes_menu.py:44,105`, `routes_roster.py:61,189`, `routes_forecast.py:52,119`, `routes_batch.py:86,173`, `routes_security.py:60,158,270`, `routes_service.py:81,193`, `routes_grievance.py:57`, `ops.py:186` (system-raised contraband incident).
- `core.py:284-289` — `touch()`: the *single* mutation path, refreshing `updated_at` from `now_wall()` and guarded by `if "updated_at" in row`. All ~50 callsites (including every cascade hop in `ops.py`, `calc.py:717`, `routes_grievance.py:217-236`, `routes_service.py:257-267`, `routes_menu.py:209`, `routes_roster.py:115-134`) go through it, so no path writes `updated_at` from the logical clock.
- `routes_forecast.py:52` and `routes_batch.py:173` — `base_row(with_version=False)` for population counts and temperature logs: these carry `created_at` but no `updated_at`/`version`, still wall-clock sourced.
- `core.py:299` — `all_rows()` sorts by `(created_at, _seq)`, backing §2.3's "ordered by `created_at` ascending … stable across pages".
- `calc.py:335-342` — `_earliest()` breaks `logged_at` ties by `created_at` (then internal `_seq`), backing §3.5's "Ties on `logged_at` are broken by earliest `created_at`" and the most-recent-`TRANSPORT_ARRIVE` rule.
- `calc.py:543-554` — `reference_cost_cents()` ranks ACTIVE cycles by descending cost with `created_at` (then `_seq`) as tiebreak, backing §3.9 Step 5.
- `core.py:173-181` — `iso()` renders exactly three fractional digits, so §2.4's existing format claim stays true.
- `core.py:321-325` — `request_meta()` also reads `now_wall()`; left undisturbed since §2.2 never claims a logical-clock source for `api_request_timestamp`.

(c) **Wording adjustments made:**
1. Avoided asserting `created_at` is the *sole* tiebreaker. The impl adds an internal insertion sequence (`_seq`) as a further tiebreak in all three ranking sites, so the sentence says only that `created_at` remains "usable as an arrival-order tiebreaker", leaving the §2.3/§3.5/§3.9 prose intact rather than narrowing it into a false universal.
2. Changed "on every row of every entity type" to "on every row of every entity type **that carries them**". The unqualified phrasing would have implied every entity has an `updated_at`, contradicting §2.4's own immutable-ledger exception for population counts and temperature readings (`base_row(with_version=False)` at `routes_forecast.py:52` and `routes_batch.py:173`) — a brand-new mismatch off the Step 7 site.
3. Framed the addition as clarifying that the existing enumeration "is closed" rather than editing the enumeration itself, so all 20 listed logical-clock fields keep their verbatim wording.

## Step 9: Complete PRD — 2026-09-03T08:33:00.000Z

**Orchestrator decision:** run the scan as three sequential file-partitioned passes rather than one pass. Rationale: `implementation/` is 3,778 lines across 12 modules with 77 endpoints; a single-agent exhaustive walk at that size reliably degrades into a partial scan (the failure mode where `PRD_COMPLETED.md` comes back byte-identical to its source because the walk never really ran). Partitioning by file guarantees every module is visited by an agent that has room for it. Passes ran strictly sequentially, each editing `PRD_COMPLETED.md` in place with `Edit` (never `Write`), so no pass could clobber another's work; each later pass spot-checked earlier passes' edits on exit and confirmed them present.

Partition:
- **Pass 1** — engine layer: `app.py`, `core.py`, `calc.py`, `ops.py`, `start.sh`, `requirements.txt`
- **Pass 2** — `routes_contract.py`, `routes_menu.py`, `routes_roster.py`, `routes_forecast.py`
- **Pass 3** — `routes_batch.py`, `routes_security.py`, `routes_service.py`, `routes_grievance.py`

### Totals

`PRD_FINALIZED.md` 616 lines / 134,669 chars -> `PRD_COMPLETED.md` 616 lines / 158,586 chars (**+23,917 chars, +17.8%**, 0 net lines — every edit in-paragraph, no new sections).

**78 changes total: 61 ambiguity-pins, 17 mismatch-revisions.**
- Pass 1: 20 changes (17 ambiguity, 3 mismatch), +6,189 chars
- Pass 2: 22 changes (17 ambiguity, 5 mismatch), +6,767 chars
- Pass 3: 36 changes (27 ambiguity, 9 mismatch), +10,961 chars

### Pass 1 — engine layer (20 changes)
- §2.1 — insert — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` counts as empty; a passing header is recorded/compared untrimmed; role names matched exactly (case-sensitive) — core.py:393-404
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A–Z/0–9 — core.py:318-325
- §2.2 — insert — ambiguity — the error envelope also carries framework failures and 5xx: unrouted path -> 404 `ERR_NOT_FOUND`, undeclared method -> 405 `ERR_METHOD_NOT_ALLOWED`, unexpected fault -> 500 `ERR_INTERNAL`; trailing slash accepted — app.py:36-50, core.py:128-130
- §2.3 — insert — ambiguity — a non-integer / decimal / present-but-empty `limit` or `offset` also reports `ERR_VALUE_OUT_OF_RANGE`; omitted takes default — core.py:424-443
- §2.3 — insert — ambiguity — filters are exact string comparisons against the field's string rendering, no match -> empty page with `total_count` 0, undeclared params ignored; `created_at` order made total by insertion order — core.py:457-463, 297-299
- §2.4 — insert — ambiguity — store is in-memory with no seed data, empty on every boot — core.py:252-267 / app.py:3-4
- §2.4 — insert — ambiguity — every rendered instant is UTC-normalised, three fractional digits **truncated** (not rounded) to whole milliseconds, trailing `Z` — core.py:173-181
- §2.4 — revise — **mismatch** — the closed "from the logical clock" enumeration wrongly included `chill_deadline_at`/`buffered_release_at`; they are fixed offsets from the client-supplied `scheduled_cook_start_at` — calc.py:375-378
- §2.5 step 5 — insert — ambiguity — one sweep in declaration order, presence tested before type per field; explicit `null` counts as absent; absent/non-object body treated as `{}`; instant/date fields fail as `ERR_INVALID_REQUEST` when unparseable (date must be exactly 10 chars `YYYY-MM-DD`); booleans never satisfy integer/number — core.py:488-519, 407-411
- §2.5 step 7 — insert — ambiguity — ranges swept in declaration order over supplied fields only; string-length bounds enforced in the same step under the same code, after all numeric ranges — core.py:525-548
- §2.7 — insert — ambiguity — decimal fields serialize as JSON numbers without trailing hundredths zeros (`0.00` renders as `0.0`) — core.py:328-337
- §2.7 — insert — ambiguity — temperatures rounded half up to 1 dp before any comparison — calc.py:301
- §2.7 — revise — **mismatch** — "Instants are compared at whole-second resolution" is false; comparisons use full parsed sub-second precision even though rendering shows milliseconds — core.py:184-199, 221-226
- §2.9 — insert — ambiguity — posture is also recomputed by any other operation that reconciles the facility's counters (batch scheduling, diet-census changes); harmless because idempotent — calc.py:439-466, ops.py:111-144
- §2.10 — insert — ambiguity — pure counter-reconciliation hops bump `version`/`updated_at` only when a reconciled value net-changed; specification-named hops bump unconditionally — ops.py:111-144 (vs. `force=True` call sites)
- §3.6 hop 3 — revise — **mismatch** — lockdown discard sets `qa_status` to `QA_HELD` only where it still reads `QA_PENDING`; any other QA status is left as-is — ops.py:154-164
- §3.6 fan-out — insert — ambiguity — the system incident carries `sanction_type`/`disposition_by_user_id` null, `narrative` copied from the declaration, `discovered_at` from the logical clock — ops.py:183-200
- §3.9 — insert — ambiguity — every incremental recompute re-runs steps 4–9 in full while steps 1–3 are adjusted incrementally; a pinned `ld_variant` is reused by later incremental recomputes — calc.py:557-613, ops.py:241-243
- §3.9 — insert — ambiguity — reconciliation also overwrites `substitution_total` — calc.py:625-627
- §3.9 — insert — ambiguity — `substitution_total` is among the incrementally maintained ledgers **not** zeroed on reconciliation invalidation — ops.py:249-261

Pass 1 judgement call: did not append `ERR_NOT_FOUND` / `ERR_METHOD_NOT_ALLOWED` / `ERR_INTERNAL` rows to the §5 table (to preserve the file's ending boundary); their ids and statuses are pinned in §2.2 prose instead.

### Pass 2 — contract / menu / roster / forecast (22 changes)
- §2.5 — revise — mismatch — cycle-completeness prerequisite (`ERR_MENU_CYCLE_INCOMPLETE`) moved ahead of the two nutrition gates in the ladder tail — routes_menu.py:163-173
- §2.5 — revise — mismatch — the late "contract-active and cycle-completeness prerequisites" pairing reduced to `ERR_CONTRACT_NOT_ACTIVE` alone — routes_menu.py:196
- §2.4 — insert — ambiguity — clock-set answers HTTP 200, `response_type` `object`, `data` carrying exactly one field `current_utc`; a bad value is `ERR_INVALID_REQUEST` — routes_contract.py:41-47
- §3.1 — insert — ambiguity — facility creation requires `contract_id` to resolve but imposes no contract-state gate — routes_contract.py:202-207
- §3.1 — revise — ambiguity — `substitution_allowance_pct` stored and echoed exactly as supplied, not quantized; §3.9 reads it at full precision — routes_contract.py create / calc.py apply_ledger
- §3.2 — insert — ambiguity — `religious_tags` checked only for being a JSON array; elements never type- or enum-checked — routes_menu.py:87,117
- §3.2 — insert — ambiguity — approval reversion on item add is scoped to `NUTRITION_APPROVED`; an `ACTIVE` cycle accepts additions and keeps its status/figures/signature; only `RETIRED` bars the add — routes_menu.py:100-129
- §3.2 — insert — ambiguity — activation's four gates run in §2.5 ladder order, not narration order: SoD before contract status, cost ceiling last — routes_menu.py:189-200
- §3.3 — insert — ambiguity — `housing_unit` stays optional even on `HOUSING_CHANGE`; omitted leaves the field untouched while the ripples still fire; movement has no state precondition — routes_roster.py:102-109
- §3.3 — revise — mismatch — segregation worker cascade: destination read after the move, clearance moves only from exactly `CLEARED`, worker `version` bumps only if something changed — routes_roster.py:117-128
- §3.3 — insert — ambiguity — a `RELIGIOUS` order with non-blank `clinical_indication` is `ERR_INVALID_REQUEST`, ahead of the diet-code family check; whitespace-only counts as empty — routes_roster.py:161-169
- §3.3 — revise — mismatch — deleted the false claim that "the window is validated before anything else"; it is checked at its §2.5 ladder position — routes_roster.py:177-187
- §3.3 — insert — ambiguity — created order's `clinical_indication` and `supersedes_diet_order_id` default to null — routes_roster.py:195,198
- §3.3 — insert — ambiguity — `verification_note` is type-checked when supplied then discarded — routes_roster.py:240
- §3.3 — insert — ambiguity — the incumbent-revocation hop is conditional on the incumbent still reading exactly `ACTIVE` — routes_roster.py:266-271
- §3.4 — insert — ambiguity — `population_count_id` must resolve but need not belong to the forecast's facility — routes_forecast.py:96-97
- §3.4 — insert — ambiguity — persisted forecast field set enumerated (segment tray figures are intermediates); lock's two gates in ladder order — routes_forecast.py:119-132,158-164
- §3.4 — insert — ambiguity — the expiry sweep is part of the write phase, after every rejection, so a refused create expires nothing — routes_forecast.py:100-110
- §3.6 — insert — ambiguity — `counted_on_board` is a required integer >= 0, range failure reported before the path facility is resolved — routes_contract.py:254-255
- §3.6 — revise — ambiguity — the audit reconciles the facility's derived counters generally (loose wording chosen because `sync_facility` reconciles all counters) — routes_contract.py:264 / calc.py:462
- §3.9 — insert — ambiguity — `ld_variant` is not swept by required/type/enum steps, so any wrong or missing value reports `ERR_LD_VARIANT_REQUIRED`, checked last — routes_contract.py:142-154
- §3.9 — revise — mismatch — re-closing a `CLOSED` contract yields `ERR_ALREADY_TERMINAL`, not `ERR_INVALID_STATE`; `DRAFT`/`ACTIVE` remain `ERR_INVALID_STATE` — routes_contract.py:167

### Pass 3 — batch / security / service / grievance (36 changes)
§3.5 production batches:
- insert — ambiguity — only `production_stage` `DISCARDED` bars a temperature log; a `SERVED` batch still accepts readings even when `qa_status` is `QA_CONDEMNED` — routes_batch.py:118-131
- insert — ambiguity — the reheat elapsed-minutes check is evaluated but never persisted — routes_batch.py:140-149
- insert — ambiguity — a temperature log bumps the batch `version` only when one of the seven `BATCH_STATE_FIELDS` moved — routes_batch.py:18-20,151-160
- insert — ambiguity — `to_stage` accepts the full six-value stage enum, terminal check reached only after the enum sweep — routes_batch.py:196-205
- insert — ambiguity — the `COOKED`-step `produced_trays` requirement fires two ladder positions ahead of the batch 404 and is ignored on every other step — routes_batch.py:200-206
- insert — ambiguity — only the `CHILLED` step re-derives all four cook-chill anchors — routes_batch.py:226-231
- revise — mismatch — a QA verdict is guarded on the QA axis alone, so permitted on a `SERVED`/`DISCARDED` batch; re-asserting the same `qa_status` is `ERR_INVALID_STATE` — routes_batch.py:258-266

§3.6 labour / sharps / contraband:
- insert — ambiguity — `medical_clearance_expires_at` stored verbatim and may already have lapsed; enrolment touches no other row — routes_security.py:46-72
- insert — ambiguity — the `OPEN` contraband hold is not scoped to the worker's own facility — routes_security.py:34-36
- insert — ambiguity — a `BARRED` (step 16) and an already-`ASSIGNED` (step 17) worker are rejected ahead of all four assignment gates — routes_security.py:97-98
- revise — mismatch — tool issue applies no terminal step, so a `BARRED` worker reports `ERR_WORKER_NOT_CLEARED`; no gate caps issues against `sharps_authorized_count` — routes_security.py:148-156,174-176
- insert — ambiguity — a `NON_SHARP` issue moves no sharps counter but still recomputes posture and bumps facility `version` — routes_security.py:174-176
- insert — ambiguity — `returned_count_verified` carries no declared range (so `ERR_INVALID_REQUEST`, never `ERR_VALUE_OUT_OF_RANGE`), enforced at step 5 — routes_security.py:200-204
- insert — ambiguity — re-declaring an already-`UNACCOUNTED` issuance is `ERR_INVALID_STATE`, a `RETURNED` one `ERR_ALREADY_TERMINAL` — routes_security.py:229-230
- insert — ambiguity — cascade hop 2 re-runs the whole §2.9 waterfall, so a `NON_SHARP` declaration can still resolve to `LOCKDOWN` — routes_security.py:240
- revise — mismatch — hop 3 is keyed on the posture hop 2 produced reading `LOCKDOWN` whatever clause put it there, not on the tool being sharp — routes_security.py:242-243
- revise — mismatch — hop 4 keyed on that same `LOCKDOWN` condition rather than on any batch having been discarded — routes_security.py:242-244
- insert — ambiguity — a directly reported incident's optional `inmate_worker_id`/`related_tool_issuance_id` are not checked for facility agreement — routes_security.py:263-269
- insert — ambiguity — both conditional `sanction_type` shape rules are `ERR_INVALID_REQUEST` at step 5, ahead of the incident 404; a re-disposition is `ERR_ALREADY_TERMINAL` — routes_security.py:316-323
- revise — mismatch — the worker `version` bumps on *every* sanctioned disposition (strike count always moves); the count is a cross-facility recount of `SANCTIONED` incidents — routes_security.py:340,356-357 + calc.py:498-503

§3.7 service records and substitutions:
- insert — ambiguity — PATCH splits `DISPUTED` (`ERR_ALREADY_TERMINAL`) from `CLOSED` (`ERR_INVALID_STATE`); an empty body is accepted, still recomputing and bumping — routes_service.py:130-137
- insert — ambiguity — close splits the same two errors, both behind the `ERR_STALE_CONTRACT_VERSION` guard — routes_service.py:151-154
- insert — ambiguity — the contract's own `status` is neither a precondition for closing a record nor changed by it — routes_service.py:150,164
- insert — ambiguity — the record's `status` is not a precondition for documenting a substitution — routes_service.py:186-191
- insert — ambiguity — the menu cycle's `status` is irrelevant in both directions when documenting — routes_service.py:188-191
- insert — ambiguity — `decision_note` accepted and discarded; a second decision is `ERR_ALREADY_TERMINAL` — routes_service.py:238-241

§3.8 grievances:
- insert — ambiguity — the grievance's optional `diet_order_id`/`meal_service_record_id` are resolved but not checked for facility agreement — routes_grievance.py:48-53
- insert — ambiguity — routing a `DIET_REVIEW` without a diet order, and a `DUAL_TRACK` without both links, are `ERR_INVALID_STATE` — routes_grievance.py:108-114
- insert — ambiguity — re-routing splits `ERR_ALREADY_TERMINAL` (terminal status) from `ERR_INVALID_STATE` (already routed) — routes_grievance.py:105-106
- revise — mismatch — either `GrievanceCoordinator` or `RegisteredDietitian` may complete either branch — routes_grievance.py:131
- revise — mismatch — the per-branch role parentheticals removed (x2 sites) — routes_grievance.py:131
- insert — ambiguity — `finding` is free-form and never persisted; only the literal `KITCHEN_AT_FAULT` on `DIET_REVIEW` raises `diet_remedy_required` — routes_grievance.py:135,146-147
- insert — ambiguity — each branch's legal origin statuses (`BRANCH_STATE`); a repeat completion of the same branch is `ERR_INVALID_STATE` — routes_grievance.py:27-28,140-143
- insert — ambiguity — `refeed_tray_count` carries no declared range and is stored verbatim whenever present, whatever the remedy — routes_grievance.py:164,196-197
- revise — mismatch — the refeed ledger hops follow the *service record's* facility's contract — routes_grievance.py:218-224
- revise — mismatch — the reinstatement branch borrows none of §3.3's guards: no `MAX_REVERIFICATIONS` ceiling, `verification_expires_at` not cleared, `requested_by_user_id` not re-anchored — routes_grievance.py:226-231 vs routes_roster.py:299-307
- revise — mismatch — the breach hops follow the *grievance's own* facility's contract, which may differ from the refeed one — routes_grievance.py:209-210,233-237

### Orchestrator verification
- `PRD.md` 616 lines / 134,197 chars; `PRD_FINALIZED.md` 616 / 134,669; `PRD_COMPLETED.md` 616 / 158,586.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` -> differs, so the scan genuinely ran (not the byte-identical no-op failure mode).
- `PRD_COMPLETED.md` still ends at the last row of the §5 error table (`ERR_COST_CEILING_EXCEEDED | 422`), retains all **72** error rows and all **5** top-level sections — no truncation, no lost content across three sequential passes.
- Steps 8 and 9 edited documentation only; `implementation/`, `test_suite/` and `test_helpers/` are untouched since Step 7's clean sweep, so the 8-round green result (`results.1..8.json`, all `92/92`) still describes the shipped artifact.

**PIPELINE COMPLETE.**
