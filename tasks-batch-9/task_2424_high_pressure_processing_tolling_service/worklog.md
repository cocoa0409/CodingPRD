# Worklog — task_2424_high_pressure_processing_tolling_service

## Step 1: Create task directory — 2026-09-02T15:59:06.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2424_high_pressure_processing_tolling_service` and its `workspace/` subdirectory. Index 2424 was pre-assigned by the invoking pipeline; no `./tasks/` scan was performed (concurrent pipelines on this host would collide on auto-allocation).

## Step 2: Generate Scaffold — 2026-09-02T17:22:48.000Z

Done. Three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_2424_high_pressure_processing_tolling_service/`, chunk files removed, and `scaffold_lint.py` reports `VERDICT: clean lint`.

## SCAFFOLD.yaml
`domain_name: hpp-tolling-service`, `api_prefix: "/"`, `difficulty_level: expert_plus`; profile = `primary_archetype: compliance_audit`, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers`, `entity_topology: graph`, `role_model: segregation_of_duties`, `consistency_model: immediate`.

- 13 entities (Customer, ProductFamily, Vessel, ColdRoom, ProductQualification, ValidationRun, CapacityContract, Lot, VesselCycle, CycleLoad, CycleLog, Deviation, ChargebackLine)
- 8 state machines (2 cyclic: ProductQualification revision rounds, CapacityContract ACTIVE<->EXHAUSTED, plus ColdRoom NORMAL<->AT_CAPACITY; Lot runs two parallel dimensions — custody and release)
- 3 OCC rules: `load-create-stale-cycle`, `release-decision-stale-lot`, `qualification-supersede-stale`
- 12 calculations, 75 ordered validations across priorities 1–14, 48 endpoints (20 GET), 67 errors, 5 roles (Customer, PlantScheduler, PlantOperator, QualityManager, FacilityAdmin)

## SCAFFOLD_DIFFICULTY_DESIGN.yaml — 19 instances / 9 rule_ids
`dual_variant_calc` 2, `combinatorial_formula` 2, `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 2, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 3.

## SCAFFOLD_CORNER_DESIGN.yaml — 95 instances (75 full recipes + 20 `excluded_because` stubs)
entities 10, state_machines 13, calculations 12, validations 24, endpoints 6, errors 16, rbac 6, cross-cutting complexity layers 6, consistency model 2. All 67 error codes are referenced; every stub cites a difficulty instance that exists; all 95 corner names are unique against the 19 difficulty names.

## Design adjudications / defects fixed while authoring §1.9
1. **`ERR_BURST_PRESSURE_INSUFFICIENT` was unreachable.** With `package_burst_pressure_mpa <= pressure_mpa` the pressure component of the suitability score is 0, capping the score at 50.00, so the same-priority `ERR_PACKAGE_NOT_SUITABLE` row (listed first) always pre-empted it. Reordered the three p9 package rows to FORMAT -> BURST -> SCORE and documented the reason inside the score row's `check:`.
2. **`ERR_EMPTY_CYCLE` was unreachable** — widened the p8 start-state gate to "SCHEDULED or LOADED".
3. **`REPROCESS_FEE_SHARE` was undefined** — added (0.50) to §1.3 with the line-minting note.
4. `POST /lots/{id}/ship` recipe used `carrier_ref`; corrected to the declared `carrier_name`.
5. Reachability setups adjudicated: CR-1 capacity 2 so the p11 cold-room posture gate can be shown pre-empting the p12 interval rule; two customers each with their own qualification/contract/pallet for the dedicated-cycle refusal; a 2027 cycle for `ERR_CONTRACT_WINDOW_MISMATCH` (qualification still valid until 2027-08-03 so `ERR_QUALIFICATION_EXPIRED` cannot pre-empt); PACKAGE_FAILURE_RATE deviations carry `cycle_load_id` so only ACCEPT is permitted, which makes `ERR_DEVIATION_DISPOSITION_NOT_PERMITTED` triggerable.
6. Lint constraint honoured: `scaffold_lint.py` check (b) rejects any `as:` not in the endpoint's §1.5 roles, so the `ERR_UNAUTHENTICATED` recipe carries its missing/unknown-`X-Role` condition via an `error_id` capture (negative-trigger path) plus prose rather than a fake role.
7. All numeric asserts are pre-computed, e.g. suitability 80.00 / 50.00 / 44.25 (vs the 44.26 per-component-rounding trap), utilization exactly 60.00 -> net 10476 (not 11640), peak 12825 x 1.25 = 16031, take-or-pay 0 / 60000 / 240000, 3000 ppm chargeback 6788, REPROCESS share 5700 of 11400.

## Step 3: Copy Shared Files — 2026-09-02T17:23:08.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2424_high_pressure_processing_tolling_service/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T17:34:58.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **435 lines**, written incrementally in six appends.

**Sections written**
- §1 Introduction (3 paragraphs, domain framing of HPP tolling)
- §2 Global Specifications — 10 subsections, domain-derived titles: 2.1 Operator Identity & RBAC, 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Common Resource Properties & Logical Clock, 2.5 Optimistic Concurrency, 2.6 Path Resolution & the 14-tier Rejection Ladder, 2.7 Precision/Rounding, 2.8 Cold-Chain & Segregation, 2.9 Conserved Ledgers & Cascade Discipline, 2.10 Segregation of Duties & Four-Eyes
- §3 Business Logic — 9 subsections (facility setup -> qualification -> contracts -> dock receipt -> scheduling/loads -> chamber run & CCP fork -> deviation adjudication -> disposition/fee allocation/inspection -> release/ship/settlement/day-close)
- §4 Endpoint Definitions — 48 rows, exactly 4 columns
- §5 Error Code Catalogue — 67 rows, exactly 2 columns

**Hard Contract reports (transcript only, not written into any file)**

```
Field coverage check:
- entities[].fields: 130 required, 130 present, 0 missing
- endpoints[].request_body/input/output keys: 100 required, 100 present, 0 missing
- endpoints[].query_params (limit, offset + all filters): all present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 75 rows across 14 tiers checked, ordering expressed as an explicit ladder in §2.6 plus per-endpoint orderings restated in §3, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write op + expected_cycle_version / expected_lot_version / expected_qualification_version + ERR_STALE_*_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 8 machines / 47 transitions checked, all from->to pairs, preconditions with error IDs and side-effect cascades expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed in prose (single-rounding suitability score; ESTIMATED vs ACTUAL fee with gross-keyed credit tier; floor-then-remainder allocation with post-remainder peak uplift; both leaker-rate variants; half-open vessel overlap + cleanout gap; closed-interval cold-room occupancy; slot ledger; take-or-pay; CCP verdict/severity; unit ledger; chargeback balance), 0 missing
- validations[] conditions: 75 checked, all matchable to their error_id in §2/§3 narrative, 0 missing
- endpoints[].side_effects / applies_to: 48 endpoints checked, all side effects and applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: 130 checked (types, defaults, initial values, enum domains, computed derivations), reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (COMPLETED_CLEAN vs COMPLETED_DEVIATED; ACCEPT/REPROCESS/REJECT adjudication; ACCEPT vs REJECT dock inspection; RELEASE/HOLD_FOR_TEST/REJECT; CANCELLED vs ABORTED terminate; ESTIMATED vs ACTUAL fee), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 874
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Tail confirmed complete:** the file ends at the last error-catalogue row, `ERR_CONTRACT_CAPACITY_EXHAUSTED | 409`, at a real section boundary — no mid-sentence truncation, no leftover append sentinel, no audit footer. All 67 scaffold error IDs and all state/enum values appear verbatim in backticks; all 5 role names and every role's `identity` are translated into §2.1 prose.

**One scaffold inconsistency resolved:** `Deviation.worst_shortfall_pct`'s field description says "max of pressure_shortfall_pct and hold_shortfall_pct" while `calculations.ccp_verdict_and_deviation_severity` computes the max over all three (including `temp_excursion_pct`). I followed the calculations table as authoritative and wrote the three-way maximum.

**Orchestrator anti-truncation verification (independent of subagent claim):** `## ` headings present for §1–§5; §4 endpoint table has 48 data rows (50 table lines incl. header+separator); §5 has 67 `ERR_` rows; `comm` diff of all `ERR_*` tokens in SCAFFOLD.yaml vs PRD.md shows only the scaffold's own literal template placeholder `ERR_XXX` missing — every one of the 67 real error codes is present. Tail ends at a complete table row. Not truncated; no regeneration needed.

## Step 6: Generate Implementation — 2026-09-02T18:15:00.000Z

Implementation complete and smoke-tested.

## Files written
All under `workspace/implementation/` (20 files, nothing else touched — `test_helpers/` and `test_suite/` were never read or written):

- Infrastructure: `start.sh` (executable, `exec python3 app.py`, flask install only when missing), `requirements.txt`, `app.py` (blueprint registration, `strict_slashes=False`, `ApiError`/400/404/405/500 envelope handlers, `PORT` env with 10000 default)
- Core: `clock.py` (logical clock, default `2026-08-01T00:00:00Z`, 3-fraction-digit formatter), `db.py` (in-memory dicts, empty on boot, no seeding; `insert`/`insert_event`/`touch` with one version bump per row per request), `errors.py` (67-code catalogue helpers), `response.py` (envelope + pagination meta), `validation.py` (tier-3 schema/query helpers), `middleware.py` (tiers 1-2 + ownership), `calc.py` (12 calculations, all `Decimal`), `services.py` (lookups, conserved ledgers, cascades), `serializers.py` (derived fields re-derived at read)
- Routes: `api_reference.py` (9), `api_qualifications.py` (8), `api_contracts.py` (5), `api_lots.py` (6), `api_cycles.py` (9), `api_loads.py` (3), `api_deviations.py` (3), `api_money.py` (5)

## Endpoints
**48/48** registered, verified by dumping `app.url_map` — exactly the PRD §4 table (including `PATCH /vessels/{id}`, `POST /operations/day-close`, `POST /_clock/set_current_utc`).

## Verification
Three smoke suites against a freshly launched `start.sh` (ports 10744/10745/10746), pyflakes clean, zero unexpected results:
- Happy path end-to-end: qualification -> 2 acceptable runs -> QUALIFY -> contract -> lot receipt/inspect -> cycle -> load -> start -> CCP log -> disposition -> leaker inspection -> deviation -> release -> ship -> day-close -> contract close -> waive.
- Deviated branch: MAJOR under-pressure -> REPROCESS cascade (fee 9166 allocated 3:2 as 5500/3666 with remainder cent, then peak x1.5 -> 8250/5499; REPROCESS chargebacks 4125/2750; pallets back to `IN_COLD_STORAGE`/`NOT_RELEASED`); CRITICAL -> `ERR_DEVIATION_ACCEPT_NOT_PERMITTED` then REJECT cascade (fee 0, loads REJECTED, pallets DISPOSED, room posture and contract slots recomputed); segregation-of-duties, four-eyes release, terminate compensation, vessel window conflict, cleanout gap, empty cycle.
- Ladder/error sweep: 40+ distinct refusals each returning the exact catalogue code and status (duplicates, ownership, stale versions, cold-chain, segregation zone, room capacity x2, basket/unit capacity, dedicated cycle, family/window mismatch, exhausted contract, expired vs. not-qualified, suitability trio, pagination and enum query validation, 401 without headers).

Trailing 90-day rescoring was confirmed to yield 5000 ppm inside the window and 0 once the cycle ages out; take-or-pay produced 3 shortfall slots / 150000 cents on a 5-slot contract with 1 consumed.

## PRD ambiguities resolved
1. **Contract/pallet customer mismatch** has no catalogue code -> `ERR_NOT_RESOURCE_OWNER` (403), placed after `ERR_CONTRACT_WINDOW_MISMATCH` and before `ERR_CONTRACT_CAPACITY_EXHAUSTED`, matching the §3.5 sentence order.
2. **Ownership (tier 6)** enforced on the scaffold's `applies_to` list plus `GET /capacity-contracts/{id}` and `GET /product-qualifications/{id}/validation-runs` (§2.1 names contracts explicitly); not on `GET /customers/{id}`, `GET /vessel-cycles/{id}` or `GET /deviations/{id}`. List endpoints silently scope to own rows for role `Customer`.
3. **`PATCH /vessels/{id}` with `status: IN_USE`** -> 400 `ERR_INVALID_REQUEST` (`IN_USE` is system-only); the body is parsed before the 404 lookup, per tier 3 before tier 4.
4. **Derived values re-derived at read** (customer balance, room occupancy/posture, contract slot ledger) so the conserved ledgers of §2.9 cannot drift; `ColdRoom.version` moves only on a posture flip and `CapacityContract.version` only on a status flip.
5. **`worst_shortfall_pct`** = max of all three shortfall percentages including the temperature excursion (§3.6 prose over the terser scaffold entity note); severity CRITICAL at >=5.00.
6. **`ValidationRun` with `leaker_count > units_tested`** -> 400 `ERR_INVALID_REQUEST` (no catalogue code exists for it).
7. **Four-eyes** applies only to `RELEASE` from `ON_HOLD_FOR_TEST`; the deviation and disposition gates apply only to outcome `RELEASE`.
8. **Cycle-log deviation row**: one deviation per deviated run, `deviation_type` = the first flag in evaluation order (UNDER_PRESSURE -> SHORT_HOLD -> TEMP_EXCURSION), full flag list kept on the log.
9. **`customers_rescored`** at day-close = total customer count (every customer is rescored, whether or not the value changes).
10. **`carrier_name`** on ship is accepted and validated but not persisted (no such entity field); `reason`, `root_cause_code` and `waive_reason` are treated as required.
11. **Terminate**: `VOIDED` loads keep `allocated_fee_cents` null and utilisation is not recomputed at terminate time (it is recomputed on the next booking/disposition, per §3.5's "next recompute" wording).

## Step 5: Generate Unit Tests — 2026-09-02T19:29:00.000Z

Test suite is complete. Final file written this session: `test_suite/test_17_concurrency_and_consistency.py` (4 tests — the three §2.5 optimistic-concurrency guards and the §2.9 immediate-cascade case).

**Files written**

Infrastructure — `test_helpers/`: `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

Tests — `test_suite/`: `conftest.py` plus 17 modules.

**Test counts**

- Queue A (`Design: Difficulty/...`, from SCAFFOLD_DIFFICULTY_DESIGN.yaml): **60 tests** in `test_01`-`test_09`, covering **19/19** non-stub instances, every one with >=2 tests.
- Queue B (`Design: Corner/...`, from SCAFFOLD_CORNER_DESIGN.yaml): **75 tests** in `test_10`-`test_17`, covering **75/75** non-stub instances, one test each.
- Total **135 tests**, one `Design:` line per test, tests-vs-tags parity in every file.

**Instances skipped by the PRD-first filter: none.** Every non-stub instance in both indices had verbatim PRD coverage that uniquely derived its asserted outcome. The only untranslated instances are the ones the design yamls themselves mark `excluded_because:` (20 corner stubs that defer to a difficulty instance, plus the 3 `cross-cutting complexity layers` and 1 `consistency model` stubs counted among them) — excluded by design, not weakened or placeholdered.

**Verification**

- `python3 -m pyflakes test_suite/*.py` -> clean; each module additionally proved by `importlib.import_module` (pyflakes cannot see through the `test_helpers` star-exports).
- Citation auditor over all 17 files -> `misses: 0`; every `PRD §x:` quote is greppable verbatim in `workspace/PRD.md` after whitespace normalisation.
- Tag auditor -> 19/19 difficulty (none under 2), 75/75 corner, no unknown tags, no tags pointing at stubs.

**One tooling note worth relaying:** my throwaway tag auditor at `/tmp/audit_tags.py` used `^\s*Design: (\S+)$`, which silently fails to match any tag whose design *section name contains spaces* (`cross-cutting complexity layers`, `consistency model`). It reported those 4 instances as uncovered even after they were written. I fixed the regex to `(.+?)` in place; anyone reusing that script (or writing a Stage 2 checker) should not assume design tags are space-free.

The isolation constraint was honoured throughout: nothing under `workspace/implementation/` was read or written, and the suite is written against `workspace/PRD.md` only.

## Step 7: Run Tests and Iterate — 2026-09-02T19:35:27.000Z

Done — clean sweep. Final state:

**Iterations run: 2**

**Iteration 1** (baseline, 8/8 rounds at 134/135): a single deterministic failure in all 8 rounds — `test_10_entities.py::test_the_control_point_record_is_written_once_and_never_edited`, asserting `ERR_DUPLICATE_CYCLE_LOG` but receiving `ERR_INVALID_CYCLE_STATE`.

**Diagnosis (STEP 1b — error precedence silence, not uniquely derivable).** Capturing the CCP record always moves the cycle out of `RUNNING` (`RUNNING -> COMPLETED_CLEAN` / `COMPLETED_DEVIATED`), so a *second* capture attempt necessarily violates the state gate too, and both checks sit in the same tier. PRD §3.6 names both refusals in one sentence without fixing precedence: "Exactly one such record exists per cycle: a second attempt is refused with `ERR_DUPLICATE_CYCLE_LOG` (HTTP 409), and a capture attempted on a cycle that is not `RUNNING` is refused with `ERR_INVALID_CYCLE_STATE`." §2.6 tier 8 lists them in the opposite order — "**State preconditions.** The target row's lifecycle state permits the requested transition, and single-occurrence records have not already been written. These yield HTTP 409" — combined with "Within a tier, the order given below applies." Two PRD-faithful readers therefore diverge: reader A follows §2.6's intra-tier order and reports `ERR_INVALID_CYCLE_STATE` (which is what the implementation does, at `api_cycles.py:create_cycle_log`); reader B follows §3.6's sentence order and reports `ERR_DUPLICATE_CYCLE_LOG`. Both 409. PRD does not determine the choice, so the exact-code assertion is not derivable; the covered part (the second attempt IS refused with 409, and the stored record is unchanged and version-less) is retained.

**Tests deleted: none.** (Partial-coverage handling per cardinal rule 1c was sufficient — the uncovered assertion was relaxed, not the test dropped.)

**Fixes applied to `test_suite/`:**
- `test_suite/test_10_entities.py` — `test_the_control_point_record_is_written_once_and_never_edited`: exact-code assertion relaxed to `validate_error_is_one_of([ERR_DUPLICATE_CYCLE_LOG, ERR_INVALID_CYCLE_STATE])` plus an explicit `status_code == 409` assertion, because the PRD names both same-tier 409 refusals for a second capture without fixing which reports first. The immutability assertions (one record only, `actual_hold_seconds == 195` unchanged, no `version`, no `updated_at`) are untouched and now actually reached. Docstring extended with the §2.6 tier-8 quote justifying the relaxation.

**Fixes applied to `test_helpers/`: none.**

**Fixes applied to `implementation/`: none** — no PRD-required check was added, removed or weakened.

**Final sweep (all 8 parallel rounds, `setsid nohup`, verified on disk as parseable JSON, no `Terminated` in `workspace/sweep.log`):**

| round | passed/total |
|---|---|
| results.1.json | 135 / 135 |
| results.2.json | 135 / 135 |
| results.3.json | 135 / 135 |
| results.4.json | 135 / 135 |
| results.5.json | 135 / 135 |
| results.6.json | 135 / 135 |
| results.7.json | 135 / 135 |
| results.8.json | 135 / 135 |

0 failed, 0 errors, 0 skipped in every round. Artifacts at `workspace/implementation/results.{1..8}.json`.

**Orchestrator independent verification:** all 8 `results.*.json` exist on disk (~40 KB each, written 19:25), parse as JSON, and each reports `passed=135 failed=0 errors=0 skipped=0 total=135`. `grep -c Terminated workspace/sweep.log` = 0, so no round was reaped. `grep -rn 'pytest.mark.skip|xfail' test_suite/ test_helpers/` = 0 matches — no test was dodged. Step 8 is NOT skipped: Step 7 made 1 `test_suite/` fix, which marks a genuine PRD silence (intra-tier 409 precedence) for Step 8 to pin.

## Step 8: Finalize PRD — 2026-09-02T19:37:30.000Z

Done. `PRD_FINALIZED.md` created with a single one-line patch.

## Line counts
- `PRD.md`: 435 lines; `PRD_FINALIZED.md`: 435 lines — 0.00% line delta (1 line revised in place, +1/-1).

## Changes
- **§3.6 (cycle log capture, line 245)** — revise — pinned the intra-tier precedence between the two same-tier 409 refusals for a CCP capture: the `RUNNING` state gate is evaluated before the single-occurrence gate, so a second capture attempt reports `ERR_INVALID_CYCLE_STATE` (the first capture having already moved the cycle out of `RUNNING`), and `ERR_DUPLICATE_CYCLE_LOG` is reserved for a capture on a cycle that is still `RUNNING` yet already carries a record; also stated that either refusal is 409 and leaves the stored record untouched — `implementation/api_cycles.py:288-294`.

## Pre-edit search log

**Edit 1 (§3.6 precedence)**
- (a) **Subject identified:** ordering of the cycle-lifecycle-state gate versus the single-occurrence/duplicate-record gate on CCP capture, plus the reachability of `ERR_DUPLICATE_CYCLE_LOG` given what a successful capture does to `cycle.state`.
- (b) **Impl paths enumerated (read/grepped):**
  - `implementation/api_cycles.py:279-355` `create_cycle_log` — full read; state check at 288 precedes duplicate check at 292; write at 306 and `cycle["state"] = COMPLETED_DEVIATED|COMPLETED_CLEAN` at 321 (unconditional — no branch leaves the cycle `RUNNING`).
  - Grepped every write of `cycle["state"]` across the whole implementation: `api_cycles.py:216` (`SCHEDULED->LOADED`), `260` (`->RUNNING`, only from `SCHEDULED`/`LOADED` per gate at 229), `321` (`->COMPLETED_*`), `382` (`->ABORTED`/`CANCELLED`), `443` (`->DISPOSITIONED`), `api_deviations.py:113` (`->DISPOSITIONED`). Confirmed **no** path ever returns a cycle to `RUNNING` after a log exists, so `ERR_DUPLICATE_CYCLE_LOG` is unreachable in practice — the wording had to keep the code alive without claiming it fires on the ordinary second attempt.
  - Grepped every writer/reader of `db.cycle_logs`: only `api_cycles.py:306` writes; `services.py:77/80`, `api_cycles.py:431`, `api_deviations.py:41` read. Single insertion site, so the single-occurrence claim has exactly one enforcement point.
  - Checked the reprocess/adjudication cascade `api_deviations.py:72-74, 108-113` -> `api_cycles.py:429 complete_disposition` for any state rollback to `RUNNING` or second log write: none.
  - Cross-checked the other same-tier gates so the §2.6-tier-8 reference stays true elsewhere: `api_cycles.py:143` (load booking state gate before `ERR_DUPLICATE_CYCLE_LOAD` at 152 — state-before-duplicate, same direction), `229`, `374`, `410`.
  - Checked `PRD.md:82` and `db.py:57 insert_event` — the "no `version`/`updated_at`, immutable" property the Step 7 test still asserts is already pinned by the PRD, so no second edit was warranted.
- (c) **Wording adjustment made:** the first draft read "a second attempt is refused with `ERR_DUPLICATE_CYCLE_LOG`, but only where the cycle is still `RUNNING`", which implicitly promised a reachable duplicate path. Rewrote to attribute the ordinary second attempt explicitly to the state gate ("Because a successful capture always moves the cycle out of `RUNNING` itself...") while leaving the duplicate refusal scoped to the still-`RUNNING`-with-record case, so an implementer keeping the (unreachable) duplicate check and one omitting it both remain behaviorally equivalent. Also anchored the precedence to the existing §2.6 tier-8 sentence rather than asserting a new global rule, keeping the load-booking and other tier-8 sites consistent.

## Step 9: Complete PRD — 2026-09-02T20:03:58.000Z

`workspace/PRD_COMPLETED.md` is written. Verified intact: 435 lines (unchanged), all 27 headings identical, all 48 endpoint rows and all 67 error rows byte-identical to the source tables, and the file still ends at `ERR_CONTRACT_CAPACITY_EXHAUSTED | 409`.

**Source vs completed:** 435 -> 435 lines; 90,186 -> 96,123 chars (+5,937). 31 lines edited, no paragraphs or sections added.

**Counts:** 27 ambiguity-pins, 5 mismatch-revisions.

**Mismatch revisions**
- §2.9 (conserved ledgers) — revise — mismatch — `priority_rank` no longer described as breaking capacity ties; now stated as recorded-but-never-consulted, since every booking names its contract explicitly — api_contracts.py:30,52 (no other reference anywhere in impl)
- §3.5 (booking guards) — revise — mismatch — the contract-must-belong-to-the-pallet's-customer rule now names `ERR_NOT_RESOURCE_OWNER` (403) and pins its position (right after the contract-window rule, before slot availability) — api_cycles.py:191
- §3.6 (start guards) — revise — mismatch — the four start conditions reordered to impl's actual order: recipe-severity (pressure then hold) -> vessel availability -> emptiness -> pallet custody — api_cycles.py:229-258
- §3.6 (start narrative) — revise — mismatch — the "`SCHEDULED` cycle is caught by the emptiness rule" claim qualified: vessel availability is evaluated first — api_cycles.py:246-252
- §3.9 (release decision) — revise — mismatch — the deviation, disposition and four-eyes gates apply only when `outcome` is `RELEASE`; `HOLD_FOR_TEST`/`REJECT` bypass all three — api_lots.py:160-175
- §3.9 (day-close) — revise — mismatch — `customers_rescored` is every registered customer, not only those whose figure changed — api_money.py:95-115

**Ambiguity pins**
- §2.1 — insert — the ownership enumeration is exhaustive: customer record, vessel cycle and deviation are not owner-checked — api_reference.py:45, api_cycles.py:450, api_deviations.py:140
- §2.2 — insert — `api_request_id` is `req_` + 20 uppercase-alnum chars — response.py:12
- §2.2 — insert — unrouted path / unsupported method answer `ERR_INVALID_REQUEST` at 404/405 — app.py:35-43
- §2.3 — insert — non-integer `limit`/`offset` are 400; empty string means omitted — validation.py:155-175
- §2.3 — insert — insertion-order tie-break; filters exact-match/conjunctive, bad enum 400, unknown id matches nothing; `Customer` lists silently narrow — db.py:92, api_lots.py:251
- §2.4 — insert — a row is versioned at most once per request even across cascade steps — db.py:75-89
- §2.4 — insert — the clock may be moved backward; echo uses the 3-digit form — clock.py:18-31, api_money.py:125
- §2.6 t3 — insert — `priority_rank`>=1 and `leaker_count`<=`units_tested` in the bounds list; explicit null = absent; supplied strings non-empty; undeclared fields ignored — validation.py:29-106
- §2.6 t8 — insert — `ERR_DUPLICATE_CYCLE_LOAD` sits in tier 8, outranking tier-9 qualification gates — api_cycles.py:151
- §2.9 — insert — all three ledgers re-derived on read; customer/room/contract versioned only when the derived posture changes — serializers.py:38-50, services.py:106-115,159-170,189-195
- §3.1 — insert — `chamber_volume_liters` integer, `max_pressure_mpa` unbounded, `hourly_operating_cost_cents` any integer — api_reference.py:94-101
- §3.1 — insert — vessel PATCH requires `status` and versions even when the value is unchanged — api_reference.py:121-130
- §3.2 — insert — `film_thickness_micron` is an integer — api_qualifications.py:36
- §3.2 — insert — `leaker_count` above `units_tested` is a tier-3 `ERR_INVALID_REQUEST` — api_qualifications.py:145
- §3.2 — insert — `decision_note` validated but not retained — api_qualifications.py:199
- §3.3 — insert — `priority_rank` integer >=1; peak windows required and mutually unordered — api_contracts.py:30-33
- §3.4 — insert — `ship_by` need not be future; receipt checks neither the qualification's owner nor its status — api_lots.py:35-40
- §3.5 — insert — `scheduled_start` need not be future — api_cycles.py:34
- §3.5 — insert — tier-8 order on booking: custody -> cycle state -> contract state -> duplicate load — api_cycles.py:139-154
- §3.5 — insert — `scheduled_from`/`scheduled_to` compare `scheduled_start`, both inclusive — api_cycles.py:475-478
- §3.6 — insert — a pallet no longer in cold storage at start yields `ERR_INVALID_LOT_CUSTODY_STATE` (409) — api_cycles.py:254-258
- §3.6 — insert — terminate `reason` required, non-empty, not retained — api_cycles.py:370
- §3.8 — insert — inspection ignores `disposition_state`; reads the frozen `allocated_fee_cents` (0 for a rejected load) — api_loads.py:29-39
- §3.9 — insert — `HOLD_FOR_TEST` stores null when `hold_reason` is omitted — api_lots.py:136,180
- §3.9 — insert — `REJECT` leaves an existing `hold_reason` in place — api_lots.py:183-187
- §3.9 — insert — `outbound_temp_c` and `carrier_name` are not retained on the pallet — api_lots.py:198-199
- §3.9 — insert — `waive_reason` required and non-empty — api_money.py:25
- §3.9/§4 — insert — day-close returns exactly its three counters, and both operational capabilities answer 200 with a report object — api_money.py:117-131

**Orchestrator independent verification:** `PRD_COMPLETED.md` is 435 lines / 96,123 chars; the five `## ` section headings are at the same line numbers as in `PRD.md` (3/11/155/307/362); §4 still carries 48 endpoint data rows (50 table lines) and §5 still carries 67 `ERR_` rows with 67 distinct error codes across the document; the file ends at the complete row `ERR_CONTRACT_CAPACITY_EXHAUSTED | 409`. Not truncated.

## Pipeline complete — 2026-09-02T20:03:58.000Z

All nine steps finished. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 files), `test_suite/` (conftest + 17 modules, 135 tests, 0 skips), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, `workspace/implementation/` (20 files, 48 endpoints, in-memory only) and `workspace/implementation/results.{1..8}.json` at 135/135 each.
