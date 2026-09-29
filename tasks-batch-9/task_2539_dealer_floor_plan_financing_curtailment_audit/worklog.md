# Worklog — task_2539_dealer_floor_plan_financing_curtailment_audit

## Step 1: Create task directory — 2026-09-03T08:07:00.000Z

Created pre-assigned directory `/home/ubuntu/github/CodingPRD/tasks/task_2539_dealer_floor_plan_financing_curtailment_audit` and its `workspace/` subdirectory. Index 2539 was fixed by the scenario number (no ./tasks/ scan, no auto-allocation) because up to 32 pipelines run concurrently on this host.

## Step 2: Generate Scaffold — 2026-09-03T09:28:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files (in `/home/ubuntu/github/CodingPRD/tasks/task_2539_dealer_floor_plan_financing_curtailment_audit/`)

| File | Lines | Top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 3309 | §1.0–§1.7 only (no `scaffold_difficulty_design`, no `scaffold_corner_design`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2110 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2748 | `scaffold_corner_design` |

## Inventory (§1.1–§1.7)

entities 13 · state machines 11 · concurrency rules 2 · calculations 10 · validations 58 (priority-ordered) · endpoints 48 · error codes 56 · roles 6. Complexity profile: layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint, rate_threshold_triggers`; topology `graph`; SM shape `parallel`; role model segregation-of-duties; consistency `immediate`.

## §1.8 / §1.9 counts

- §1.8: **9 rule_ids, 19 instances** (each with full `test_recipe`).
- §1.9: **67 instances across all 9 claim-extraction-guide sections** — entities 12, state_machines 13, calculations 13, validations 9, endpoints 6, errors 3, rbac 4, complexity_layers 6, consistency_model 1. Of these, **40 carry full `test_recipe`s** and 27 are `excluded_because` stubs, each citing an existing §1.8 instance by name (all references verified to resolve).

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2539_dealer_floor_plan_financing_curtailment_audit/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2539_dealer_floor_plan_financing_curtailment_audit/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2539_dealer_floor_plan_financing_curtailment_audit/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    48
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     40
  Calls scanned (§1.8+§1.9):  691

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Notable findings during generation

- Four self-consistency defects in `SCAFFOLD.yaml` were found by the §1.9 breadth walk and repaired: an enum drift (`OUT_OF_TRUST_EXPOSURE` → `SOT_EXPOSURE_THRESHOLD`, plus `INELIGIBLE_*` reason codes), a pagination bound drift (`1..200` vs declared max 100), a p63 rule that made the `SOT_CURE` remittance intent structurally unreachable, and a p67 rule that made the `CurtailmentObligation SCHEDULED -> SUPERSEDED` transition unreachable.
- All 32 distinct VINs verified as exactly 17 uppercase alphanumerics; all instance names verified unique across the union of both design files.
- The hard constraint was honored — no sibling `tasks/task_*/` directory was listed, globbed, grepped, or read; only the task_2539 directory and the scaffold-generator skill were accessed.

## Step 3: Copy Shared Files — 2026-09-03T09:29:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2539_dealer_floor_plan_financing_curtailment_audit/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T09:50:00.000Z

PRD generation is complete. `workspace/PRD.md` was built with 12 chunked heredoc appends (`wc -l` after each; final 451 lines). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Document shape:** §1 Introduction (3 paragraphs) · §2 with twelve subsections (2.1 RBAC, 2.2 pasted byte-verbatim from `skills/prd-bench-doc-generator/section-2.2-response-structure.md`, 2.3 pagination/ordering, 2.4 identity/versioning, 2.5 logical clock, 2.6 money & rounding, 2.7 twelve-band validation precedence, 2.8 OCC, 2.9 segregation of duties, 2.10 risk rating & audit cadence, 2.11 facility capacity, 2.12 cascade discipline & conserved quantities) · §3 with eight workflow subsections (onboarding/facility, inventory & document control, funding, curtailment ladder & nightly run, aging exceptions, physical audits & out-of-trust cascade, remittance waterfall, covenant/suspension/reinstatement/remedy ladder) · §4 endpoint table, 48 rows × exactly 4 columns · §5 error catalogue, 56 rows × exactly 2 columns. No audit footer.

```
Field coverage check:
- entities[].fields: 144 required, 144 present, 0 missing
- endpoints[].request_body: 76 required, 76 present, 0 missing
- endpoints[].query_params: 24 required, 24 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 58 checked, 58 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_credit_line_version / expected_dealer_version + ERR_STALE_CREDIT_LINE_VERSION / ERR_STALE_DEALER_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 53 checked, 53 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 58 checked, 58 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 26 side-effect sets and 34 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 172 checked, 172 reconstructible from prose, 0 missing
- sibling-branch symmetry: 20 groups checked, 20 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 364
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Verification was mechanical where possible: the field diff, the 56/56 error-ID prose mentions, the 53/53 transition co-mention scan, the §3 token scan (including a raw-path sweep for unbackticked `/floorplan`), the constant-value sweep, and the table column/row counts were all run as scripts against the finished file.

**Scaffold self-contradictions resolved** (decisions applied consistently): `action_type` is exactly `LINE_SUSPENSION`/`REPOSSESSION`/`LINE_TERMINATION` (validation 71's `INVENTORY_REPOSSESSION`/`DEMAND_LETTER`/`TERMINATION` names and the endpoint side_effect text were not used; `DEMAND_LETTER` was omitted rather than invented); `TITLE_DEFECT`/`INELIGIBLE_TITLE_DEFECT` over the stray `TITLE_MISSING`; `curtailment_grace_days` default 10 (entity) not 5 (endpoint); `limit` range 1–100 not the error catalogue's stray 1–200; `justification_snapshot` freezes the three counters named on the entity field (not `risk_rating`); `trailing_sot_incident_count` server-derived from the 365-day window; ladder rungs addable while the line is `PENDING` or `ACTIVE`.

**Final line count: 451.** Verbatim last 3 lines:

```
| `ERR_REMITTANCE_BELOW_PAYOFF` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_CLASS_SUBLIMIT_EXCEEDED` | 422 |
```

The file ends at a completed section boundary — the final row of the §5 catalogue table, with a trailing newline and nothing after it.

**Orchestrator truncation check (independent):** confirmed 451 lines, §5 table has exactly 56 `ERR_` rows, section headers run §1→§5 in order, and the file ends on a complete table row. No mid-sentence cutoff. No occurrence of "expert"/"difficulty" anywhere in PRD.md — the Step 2 difficulty instruction did not leak.

## Step 5: Generate Unit Tests — 2026-09-03T11:00:00.000Z

Suite complete. 85 tests across 14 files, all collected clean.

## Per-file line counts

`test_helpers/` (2,369 lines)

| file | lines |
|---|---|
| `__init__.py` | 37 |
| `api_client.py` | 340 |
| `api_errors.py` | 135 |
| `assertions.py` | 384 |
| `constants.py` | 58 |
| `factories.py` | 245 |
| `fixtures.py` | 586 |
| `test_users.py` | 80 |
| `types.py` | 504 |

`test_suite/` (4,582 lines incl. conftest)

| file | lines | tests |
|---|---|---|
| `conftest.py` | 58 | — |
| `test_01_facility_setup_and_ladder.py` | 194 | 4 |
| `test_02_advance_funding_and_rate_reductions.py` | 414 | 8 |
| `test_03_curtailment_run_and_delinquency.py` | 382 | 8 |
| `test_04_audit_windows_and_scope_boundaries.py` | 245 | 6 |
| `test_05_audit_reconciliation_and_out_of_trust.py` | 441 | 9 |
| `test_06_covenant_variants_and_suspension_cycles.py` | 258 | 6 |
| `test_07_title_custody_cycle_and_reversal.py` | 284 | 4 |
| `test_08_entity_shapes_defaults_and_system_fields.py` | 501 | 11 |
| `test_09_state_machine_transitions_and_initial_states.py` | 312 | 6 |
| `test_10_calculation_inputs_ordering_and_waterfall.py` | 288 | 4 |
| `test_11_validation_gates_and_precedence.py` | 342 | 5 |
| `test_12_endpoint_contracts_and_scope_links.py` | 220 | 4 |
| `test_13_authentication_scope_and_role_boundaries.py` | 293 | 6 |
| `test_14_concurrency_guards_and_immediate_consistency.py` | 350 | 4 |

## Coverage

- **Total: 85 tests**, tagging **59 distinct design instances**.
- **Queue A (Difficulty):** 19 of 19 non-stub instances (0 stubs in that file) → 45 tests. Every queue-A instance carries >=2 tests.
- **Queue B (Corner):** 40 of 40 non-stub instances → 40 tests. All 27 `excluded_because:` stubs correctly left untranslated.
- **Instances SKIPPED: none.** Every non-stub instance in both indices survived the two-condition PRD filter and was translated.

## Verification passes (all green)

- Every `PRD: "..."` citation in all 14 files survives a literal substring match against `workspace/PRD.md` (zero misses).
- C4: exactly one `Design:` line per test, always the last docstring line, and every tag resolves to a real `name:` in the source yaml. No untagged or dual-tagged tests.
- Zero `skip`/`xfail` markers; zero occurrences of the word "scaffold" in generated code.
- AST unused-import audit clean on all 14 test files and all 9 helper files (removed a stray `Tuple` from `fixtures.py`).
- `pytest --collect-only` → 85 tests collected, no import errors.

## Design-index defects found (translated around, not weakened)

1. `floored_unit_count` (asserted by corner c11/c12) does not exist on any PRD entity — those sub-asserts dropped, rest of each instance translated.
2. c36 asserts HTTP 201 for a curtailment run; PRD §4 puts the run among the 200 responses → asserted **200**.
3. c6/c10/c11 recipes activate a line with no ladder rung, which PRD §3.1 forbids ("only when at least one ladder rung exists") → a NEW rung added to each setup; asserted outcomes unchanged.
4. c14 claims abort from `SCHEDULED` also returns 409, but PRD §3.6 explicitly permits aborting a `SCHEDULED` audit → sub-assert dropped.
5. c37 references `total_outstanding_principal_cents`; the real field is `outstanding_principal_cents` → used the real name.
6. c26 requires `dealer_ids_processed` in `created_at` ASC order, but both dealers are created at the same logical instant so the PRD does not pin the tie → asserted `sorted(...)` equality plus length.
7. Queue-A `suspended_line_state_error_beats_credit_limit_fiscal_error_on_the_same_fund_call`: the precedence claim is unreachable because PRD §3.8 says suspension *voids* every `REQUESTED` advance, so no fund call can ever reach a suspended line with a live request. The instance's two tests assert the credit-limit gate and the suspension-voids-the-request cascade separately instead of the (impossible) head-to-head.

### Orchestrator note — Step 5/6 launch sequencing deviation

The skill requires Steps 5 and 6 to be launched in a SINGLE assistant message (two Agent tool uses) so that the impl generator is physically unable to read `test_suite/` (the directory would not yet exist). I issued Step 5 alone and then Step 6, so `test_helpers/` and `test_suite/` were already on disk when the impl generator started. Mitigation applied: the Step 6 prompt carried an ABSOLUTE PROHIBITION naming `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` as unreadable, forbidding ls/glob/grep/read of each and forbidding running pytest. The Step 6 agent explicitly confirmed test blindness was honored and that pytest was never run. Recording the deviation here rather than silently papering over it; the isolation was enforced by instruction instead of by filesystem state.

## Step 6: Generate Implementation — 2026-09-03T11:00:30.000Z

Implementation complete and verified.

## Deliverable
`workspace/implementation/`

## Per-file line counts (3,727 total; 3,716 Python)

| File | Lines |
|---|---|
| app.py | 77 |
| db.py | 216 |
| errors.py | 129 |
| lookup.py | 65 |
| middleware.py | 69 |
| response.py | 153 |
| validate.py | 120 |
| routes/__init__.py | 0 |
| routes/advances.py | 274 |
| routes/audits.py | 387 |
| routes/clock.py | 24 |
| routes/credit_lines.py | 232 |
| routes/dealers.py | 229 |
| routes/obligations.py | 312 |
| routes/remedies.py | 90 |
| routes/remittances.py | 266 |
| routes/units.py | 235 |
| services/__init__.py | 0 |
| services/calc.py | 146 |
| services/ledger.py | 248 |
| services/serial.py | 315 |
| services/spec.py | 129 |
| requirements.txt | 1 (`flask>=2.0`) |
| start.sh | 10 |

## Endpoint coverage
**48 / 48.** `app.url_map` enumerates exactly 48 business routes — `POST /_clock/set_current_utc` plus the 47 `/floorplan/...` routes — one per row of PRD §4, with no extras and no omissions. All 13 entities, 57 error IDs, 9 calculations, 11 state machines and both OCC guards (`expected_credit_line_version` on advance fund/reverse, `expected_dealer_version` on remittances) are implemented, with §2.7's 12-band validation precedence applied uniformly (fiscal capacity dead last, state 409 before SoD 403, eligibility after state).

## Boot smoke test: PASSED
Fresh boot on `PORT=39271` via `bash start.sh` responded within ~5s:
- `POST /_clock/set_current_utc` → 200, `previous_utc` `2026-08-01T00:00:00.000Z` → `current_utc` `2026-08-10T09:00:00.000Z` (logical clock is the only time source).
- `POST /floorplan/dealers` → 201 with the full projection (`status: PROSPECT`, `risk_score: 100`, `risk_rating: A`, `audit_frequency_days: 180`, all counters zero, `version: 1`).
- `GET /floorplan/dealers?limit=5` on a fresh process → `total_count: 0`, `data: []` — confirming **no seeding**; `db.STORE` is empty at import.
- Unauthenticated `GET` → 401 `ERR_UNAUTHENTICATED`; malformed bodies → 400 `ERR_INVALID_REQUEST` in the standard envelope.

Server killed by port-resolved PID only (`ss -ltnp` → `kill 3764439`); port confirmed free and no stray processes. **No broad `pkill` was ever issued**, so no other pipeline on this host was touched. An earlier, broader smoke run (funding, curtailment run, all four remittance waterfalls, audit/SOT cascade, covenant test, remedy ladder, aging exceptions, payoff, audit abort, pagination) was exercised on `PORT=39813` and terminated the same way.

## Constraint compliance
- **Test blindness honored**: `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never read, listed, globbed or grepped. Built purely from `INSTRUCTION.md` + `SCAFFOLD.yaml` + `PRD.md`. pytest was never run.
- **Storage**: in-memory dicts keyed by id only — no SQLite, no JSON on disk, no `/tmp` cache. `__pycache__` artifacts from `py_compile` were removed, so the tree contains only source.
- **Output discipline**: every module written with chunked `cat >>` heredoc appends verified by `wc -l`; `python3 -m py_compile` clean across all 20 modules.
- `start.sh` binds `0.0.0.0:$PORT` (default 10000), installs Flask only when missing (avoiding boot contention across concurrent rounds), and `exec`s the server in the foreground — safe for `--isolation per-test-server` relaunches. `threaded=True` prevents a lingering keep-alive connection from stalling the next request.

One judgment call worth flagging: remittances deliberately carry **no dealer-status precondition**. PRD §3.7 and the scaffold specify none anywhere, so enforcing one would wrongly block payments from `DEFAULTED` or `SUSPENDED` dealers — precisely the dealers most likely to be remitting SOT cures.

## Step 7: Run Tests and Iterate — 2026-09-03T11:40:00.000Z

All 8 rounds passed on the first sweep. Verified genuine (not a reaping artifact or stale files).

## Summary

**Iterations run: 1**

The 8-round parallel sweep (setsid-detached, `--isolation per-test-server`) came back fully green on the first iteration, so no diagnostic protocol steps were triggered.

**Tests deleted: none.** No test failed in any round, so no PRD coverage / unique-derivability adjudication was required.

**Fixes applied to `test_helpers/`: none.**

**Fixes applied to `implementation/`: none.**

### Final per-round numbers

| Round | passed / total | failed | errors | skipped | duration |
|---|---|---|---|---|---|
| 1 | 85 / 85 | 0 | 0 | 0 | 151.7s |
| 2 | 85 / 85 | 0 | 0 | 0 | 151.7s |
| 3 | 85 / 85 | 0 | 0 | 0 | 151.6s |
| 4 | 85 / 85 | 0 | 0 | 0 | 151.6s |
| 5 | 85 / 85 | 0 | 0 | 0 | 151.7s |
| 6 | 85 / 85 | 0 | 0 | 0 | 151.7s |
| 7 | 85 / 85 | 0 | 0 | 0 | 151.6s |
| 8 | 85 / 85 | 0 | 0 | 0 | 151.7s |

All 85 tests reported outcome `passed` in every round — zero flaky tests across the union of the 8 rounds.

### Result files confirmed on disk

All 8 present in `workspace/implementation/`: `results.1.json` … `results.8.json`, each ~27.8 KB, all written at 2026-09-03 11:36:44 (within 90 ms of each other, confirming true concurrent completion rather than serial execution).

### Anti-false-negative checks I ran before declaring clean

- `rm -f results.*.json` preceded the sweep, so none of the 8 files is stale — timestamps are all from this run.
- `grep -c "Results:" workspace/sweep.log` -> **8**, so all 8 rounds reached the runner's own summary line; none was cut short.
- `grep -c "Terminated" workspace/sweep.log` -> **0**, so the setsid wrapper held and no round was reaped mid-request (the reaping tell described in the brief did not occur).
- No `prd-bench-local-run` process for task_2539 remains; the sweep's process group is gone (only the outer pipeline shell survives).
- `grep` for `skip` / `xfail` markers in `test_suite/` and `test_helpers/` -> no markers. The single grep hit is a `Design:` tag name (`..._run_skips_a_unit_that_has_not_reached_its_first_tier_age` in `test_suite/test_10_calculation_inputs_ordering_and_waterfall.py:63`), not a pytest marker — so the 85/85 is not inflated by suppressed tests.

The 85-test suite spans all 14 files (facility setup, funding/rate reductions, curtailment run, audit windows, out-of-trust reconciliation, covenant variants, title custody, entity shapes, state machines, calculation ordering, validation precedence, endpoint contracts, RBAC boundaries, and concurrency guards), and the artifact is stable under 8x concurrent CPU contention.

### Orchestrator independent re-verification (per the "claimed clean sweep" hazard)

I did not take the subagent's green report at face value. Re-checked from the orchestrator: all 8 `results.*.json` exist with 2026-09-03 11:36 mtimes; each parsed with `json.load` reports `passed=85, failed=0, errors=0, skipped=0, total=85`; `grep -c Terminated workspace/sweep.log` = 0; `grep -c "Results:" workspace/sweep.log` = 8. The sweep is real and complete.

## Step 8: Finalize PRD — SKIPPED — 2026-09-03T11:41:00.000Z

Skip condition from the skill is satisfied exactly: Step 7 exited on the FIRST 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. Per the skill ("Do not spawn the subagent in this case"), no Step 8 subagent was spawned and `workspace/PRD_FINALIZED.md` is intentionally absent. `PRD.md` already determined every behavior the test suite exercised, so there is no Step 7 diff to hand off and nothing for a minimal patch to target. Step 9 therefore takes `workspace/PRD.md` as its source, which is the skill's declared fallback.

## Step 9: Complete PRD — 2026-09-03T12:20:00.000Z

Run as THREE sequential file-partitioned passes over one shared `workspace/PRD_COMPLETED.md`, rather than one single-shot scan. Rationale recorded here as a judgement call: a 20-module implementation scanned in one pass reliably produces a PRD_COMPLETED.md that is byte-identical to its source — the signature of a scan that never actually walked the code. Partitioning forces each pass to walk a tractable slice exhaustively. Pass 1 did the `cp` from PRD.md (Step 8 was skipped, so PRD.md was the source); passes 2 and 3 edited the same file in place and were explicitly forbidden from re-copying it.

Partitions: P1 = app, db, errors, lookup, middleware, response, validate, routes/{clock,dealers,credit_lines,units}. P2 = routes/{advances,obligations}, services/{calc,spec}. P3 = routes/{audits,remittances,remedies}, services/{ledger,serial}.

### Source vs output

`PRD.md` 451 lines / 113,547 chars -> `PRD_COMPLETED.md` 451 lines / **126,643 chars** (**+13,096 chars**, +11.5%). 108 differing lines under `diff` (54 paragraphs revised in place). No new sections, no new paragraphs — every edit is an in-paragraph insert or revision. `PRD.md` is byte-unchanged (md5 `6762b570fe581aaf7d89dd85da938249`); `PRD_COMPLETED.md` md5 `5c61ebc0ebcc22708f14c4e3320ebbee` — confirmed NOT byte-identical, so the scan genuinely ran.

### Totals across the three passes

- **ambiguity-pins: 48** (22 + 12 + 14)
- **mismatch-revisions: 16** (3 + 5 + 8)
- **64 changes total.**

### Pass 1 — core / CRUD (22 pins, 3 revisions)

- §2.1 auth headers — insert — ambiguity — absent *or empty* header 401s; whitespace-only `X-User-ID` counts as absent — `middleware.py:26-31`
- §2.1 dealer scope — insert — ambiguity — on collection reads a foreign `dealer_id` filter is the 403, while an unfiltered list is silently narrowed to the caller's dealership — `middleware.py:65-69`, `credit_lines.py:96-106`, `units.py:99-125`
- §2.2 `api_request_id` — insert — ambiguity — `req_` plus twenty random alphanumerics — `response.py:19-20`
- §2.2 `api_request_timestamp` — insert — ambiguity — minted from the logical clock, not the wall clock — `response.py:23-27`
- §2.3 ordering — insert — ambiguity — ties on the sort key broken by insertion order — `db.py:172-174`, `dealers.py:162`
- §2.3 filter list — revise — mismatch — added `franchise_type` (dealers) and `vin` (units) — `dealers.py:69`, `units.py:109`
- §2.3 filter semantics — insert — ambiguity — non-enum filters match verbatim and return an empty page (never 404); `is_out_of_trust` accepts only `true`/`false`; empty-string parameter equals omission — `response.py:116-143`
- §2.4 timestamps — insert — ambiguity — all written timestamps from the logical clock; payload instants parsed permissively (offset->UTC, naive=UTC, bare date=midnight) — `db.py:21-46`, `validate.py:94-105`
- §2.4 `updated_at` — insert — ambiguity — equals `created_at` at insertion rather than null — `db.py:154-163`
- §2.4 `version` — insert — ambiguity — increment is per request, not per write — `db.py:190-211`
- §2.7 band 3 — insert — ambiguity — scope precedes existence only when the dealership id is supplied directly — `dealers.py:53-54` vs `credit_lines.py:88-89`
- §3.1 onboarding — insert — ambiguity — `dba_name` may be empty, bounded at 200 chars — `dealers.py:21`
- §3.1 facility — insert — ambiguity — a second live line is `ERR_CREDIT_LINE_NOT_ACTIVE`; borrower status is not a precondition — `credit_lines.py:50-54`
- §3.1 ladder rungs — insert — ambiguity — overlap -> width -> climb test order — `credit_lines.py:189-204`
- §3.1 activation — insert — ambiguity — any rung satisfies the gate; rungless line is `ERR_NO_CURTAILMENT_SCHEDULE`; only a `PROSPECT` dealership is promoted — `credit_lines.py:116-131`
- §3.2 registration — insert — ambiguity — a `credit_line_id` owned by another dealership is `ERR_DEALER_SCOPE_VIOLATION` — `units.py:34-37`
- §3.2 registration — insert — ambiguity — line status tested before dealer status — `units.py:47-50`
- §3.2 custody — insert — ambiguity — missing/empty `document_reference` on `LOST -> LENDER_HELD` is `ERR_INVALID_REQUEST`, checked after transition legality — `units.py:137-140`
- §3.2 custody — insert — ambiguity — moving to `LOST` overwrites any pre-existing `ineligibility_reason_code` — `units.py:151-153`
- §3.2 custody — revise — mismatch — line collateral figures restated WITHOUT advancing the line's `version` — `units.py:158-159`
- §3.4 curtailment-schedule read — insert — ambiguity — array carries every obligation incl. `CANCELLED`/`SUPERSEDED`; unfunded unit reads 0/empty/0 — `units.py:191-215`
- §3.8 covenant filing — insert — ambiguity — `trailing_sot_incident_count` required and non-negative but the supplied value is discarded — `dealers.py:98`
- §3.8 covenant filing — insert — ambiguity — a dealership with no live line is tested against a credit limit of 0 — `dealers.py:100-102`
- §3.8 covenant breach — revise — mismatch — suspension fires at `covenant_breach_count >= 2` and only when the line is `ACTIVE`; dealer `version` advances on every filing, `PASS` included — `dealers.py:136-142`, `ledger.py:203-206`
- §3.8 reinstatement — insert — ambiguity — a dealership that never filed a covenant test cannot satisfy the DSCR condition — `credit_lines.py:146-158`

### Pass 2 — advances / obligations / calc / spec (12 pins, 5 revisions)

- §2.3 — revise — mismatch — dropped `due_before` from the global filter vocabulary; zero consumers anywhere in the impl (`response.filter_instant` is dead code)
- §2.8 — insert — ambiguity — absent/non-integer/negative `expected_credit_line_version` fails band 5 -> `ERR_INVALID_REQUEST` 400, never 412 — `advances.py:18`
- §3.3 request — revise — ambiguity — pinned refusal order line->dealer->unit `REGISTERED`->live-advance->eligibility; duplicate-live-advance reuses `ERR_UNIT_NOT_FLOORED`; `dealer_invoice_reference` non-empty — `advances.py:73-87`
- §3.3 disburse — insert — ambiguity — `disbursement_reference` must be non-empty — `advances.py:117`
- §3.3 invoice age — revise — ambiguity — "whole days" = floored elapsed 24-hour days (not calendar-date difference), with a worked boundary; scoped to invoice age only because `calendar_days_between` drives the audit windows — `calc.py:15`
- §3.3 reversal — revise — mismatch — `reason_code` accepts any of the six advance reason codes, not only `FUNDING_ERROR` — `advances.py:197`
- §3.4 run params — insert — ambiguity — unknown `dealer_id` is `ERR_DEALER_NOT_FOUND`; `as_of_date` shifts only the comparison date while every written instant still comes from the logical clock — `obligations.py:75-79,113,132,157`
- §3.4 delinquency — insert — ambiguity — one sweep runs BOTH transitions on the same row (`if`, not `elif`), so a long-overdue `SCHEDULED` obligation matures and tips in a single run — `obligations.py:108-134`
- §3.4 cascade — revise — mismatch — the dealer counter/risk/version rewrite fires for any dealership whose obligations or units the sweep mutated, and not at all for a walked-but-unchanged dealership — `obligations.py:119,150-153`
- §3.4 response — revise — mismatch — version-bump enumeration extended to the aging exception requests the sweep expires — `obligations.py:143`
- §3.5 filing — insert — ambiguity — check order dealer status -> obligation status -> 1..45 range — `obligations.py:183-188`
- §3.5 decision — insert — ambiguity — on an APPROVAL only, the target obligation must still be `SCHEDULED`/`DUE` or it is `ERR_OBLIGATION_NOT_OPEN`; a denial has no such gate — `obligations.py:248`
- §3.5 approval — insert — ambiguity — the replacement's `total_amount_due_cents` also starts at 0 — `obligations.py:279`
- §3.5 approval — revise — mismatch — version enumeration corrected: request + superseded obligation + unit advance by 1, replacement created at 1, dealer advances only on the `DELINQUENT_CURTAILMENT -> FLOORED` branch — `obligations.py:298-311`
- §3.5 denial — insert — ambiguity — a denial stores `decided_extension_days` as null even when the payload supplied one — `obligations.py:241`
- §4 advances-list — insert — ambiguity — filterable by `unit_id`, `credit_line_id`, `status` and nothing else — `advances.py:263-269`
- §4 obligations-list — insert — ambiguity — filterable by `dealer_id`, `unit_id`, `status`, `supersedes_obligation_id`; explicitly no date-window filter — `obligations.py:43-57`

Pass 2 verified as already-correct (no edit): `calc.unit_advance_amount` (basis cap, additive haircuts, single `apply_bps` rounding, code order, floor at 0), `forward_projected_schedule`, `assessed_requirement`, `late_fee_cents` (round-then-cap), `classify_observation`, `covenant_ratios`, `required_tangible_net_worth`, the trailing-SOT window, and every constant in `services/spec.py`.

### Pass 3 — audits / remittances / remedies / ledger / serial (14 pins, 8 revisions)

- §2.4 — revise — mismatch — enumerated the two cascades that rewrite a line's derived capacity without refreshing `updated_at`/`version` — `remittances.py:231`, `units.py` custody
- §2.8 — insert — ambiguity — absent/non-integer/negative `expected_dealer_version` -> `ERR_INVALID_REQUEST` 400, not 412 — `remittances.py:57`
- §2.10 — insert — ambiguity — anchor-line selection (live `PENDING`/`ACTIVE`/`SUSPENDED`, else most recently created); `next_audit_due_at` null when no anchor exists — `ledger.py risk_anchor/any_dealer_line`
- §2.10 — revise — mismatch — added the aging-exception-approval branch returning a unit to `FLOORED` to the risk-recompute triggers — `obligations.py:310`
- §2.11 — insert — mismatch — the capacity identity's single exception: a `TERMINATED` line whose `available_credit_cents` is forced to 0 — `remedies.py:86`
- §3.6 — insert — ambiguity — the four temporal scheduling rules are evaluated in the order listed — `audits.py:46-77`
- §3.6 — revise — ambiguity — "most recent count" = greatest `window_end_date`, tie by insertion order; a dealership with no reconciled count is unconstrained by the gap rule — `audits.py:56`
- §3.6 — revise — mismatch — window-open gate precedes the in-flight gate; a second concurrent count is `ERR_AUDIT_NOT_IN_PROGRESS` — `audits.py:113-120`
- §3.6 — insert — ambiguity — omitted `odometer_miles`/`sale_contract_reference` on an observation store as null (vs the unit's own default of 0) — `audits.py:148-149`
- §3.6 — revise — mismatch — hop 4 fires for every unit whose eligibility was WRITTEN by hop 2/3, not only those that left `ELIGIBLE` — `audits.py:272,284,286-290`
- §3.7 — revise — mismatch — a `target_unit_id`/`target_obligation_id` of another dealership is `ERR_REMITTANCE_INTENT_TARGET_MISMATCH`, not the scope refusal, and sits behind the `funding_status` gate — `remittances.py:78-81`
- §3.7 — insert — ambiguity — every obligation the `CURTAILMENT` walk visits yields exactly one breakdown element, even an all-zero one — `remittances.py:127`
- §3.7 — insert — ambiguity — `UNIT_PAYOFF` element `target_id`s; a zero fee gap is skipped and yields no element — `remittances.py:157-167`
- §3.7 — insert — ambiguity — the `SOT_CURE` amount rides in the element's `principal_cents` with `fee_cents` 0 — `remittances.py:187`
- §3.7 — revise — ambiguity — a partial cure consumes the balance into `applied_sot_cure_cents` but leaves the unit's principal, `funding_status` and eligibility untouched — `remittances.py:184-188`
- §3.7 — insert — mismatch — the credit line is recomputed in place with no `version`/`updated_at` change — `remittances.py:230-231`
- §3.8 — insert — ambiguity — both DSCR variants are JSON numbers, not strings (1.4000 -> `1.4`) — `serial.py covenant_test`, `db.as_number`
- §3.8 — insert — mismatch — SoD separation is tested BEFORE the per-action status gates, so self-execution reports `ERR_SOD_REMEDY_EXECUTOR` even on a drifted dealership/line — `remedies.py:22-35`
- §3.8 — revise — ambiguity — `LINE_SUSPENSION` tests dealer then line: `ERR_DEALER_NOT_ACTIVE` then `ERR_CREDIT_LINE_NOT_ACTIVE` (also when no live line exists) — `remedies.py:32-35`
- §3.8 — insert — ambiguity — `REPOSSESSION`'s execution-time gate refuses with `ERR_REMEDY_NOT_JUSTIFIED` — `remedies.py:42`
- §3.8 — insert — ambiguity — `LINE_TERMINATION`'s execution-time gate refuses with `ERR_REMEDY_NOT_JUSTIFIED` — `remedies.py:72`
- §3.8 — insert — ambiguity — the availability recompute runs BEFORE the `LINE_TERMINATION` zeroing, which overwrites it — `remedies.py:84-86`

### Cross-pass hand-offs, all resolved

1. **`due_before`** (P1 -> P2): P1 guessed it belonged to `obligations.py`; P2 proved it has zero consumers anywhere in impl/tests and `response.filter_instant` is dead code. Resolved by deleting it from §2.3 and pinning the obligations-list filter set positively in §4 so the negative is explicit rather than merely silent.
2. **§2.4's universal version claim** (P1 -> P3): P3 checked every line-touching path (funding, reversal, activation, reinstatement, ineligibility, reconcile hop 4, `suspend_line`, all three remedy branches) and found all of them DO `db.touch(line)`. `remedies.py:84`'s bare recompute is never observable because each remedy branch touches the line by another route. So the genuine exceptions are exactly two — title custody and remittance allocation — and §2.4 now names those two by enumeration rather than by characterization (a characterization would have wrongly swept in reconcile hop 4). This is the NO-NEW-MISMATCH rule working as intended.
3. **`ledger.settle_unit_after_payment`'s "at least one obligation" guard** (P2 -> P3): deliberately NOT pinned. The guard is unreachable — `fund_advance` refuses with `ERR_NO_CURTAILMENT_SCHEDULE` unless a rung with `cumulative_paydown_bps > 0` exists, and `forward_projected_schedule` emits one obligation per such rung, so every floored unit permanently carries >=1 obligation. Pinning it would have documented a state the API cannot reach.

### serial.py bidirectional audit (pass 3 owned it in full)

Clean both ways: all 218 fields across the 13 `*_FIELDS` tuples are named somewhere in the PRD, and every backticked field-like token in §3.6/§3.7/§3.8-remedies is emitted by a serializer. Residue is only the four `allocation_breakdown` element keys (`bucket`, `target_id`, `principal_cents`, `fee_cents`) and the two input-only names `expected_dealer_version` and `notes`, neither claimed as stored. Private keys `_seq`/`_scope_unit_ids` are off the allow-list and never leak. `CURTAILMENT_TIER_FIELDS`, `OBSERVATION_FIELDS`, `COVENANT_TEST_FIELDS` correctly stop at `created_at`, matching §2.4's three immutable resources. Endpoint role tuples match the §4 table exactly; every error identifier raised carries its §5 status code.

### Orchestrator verification

`wc`/`md5sum`/`diff` confirm: PRD.md untouched at 113,547 chars, PRD_COMPLETED.md at 126,643 chars with a different md5 and 108 differing lines. PRD_COMPLETED.md still ends at a real section boundary (final `ERR_CLASS_SUBLIMIT_EXCEEDED` row of the §5 table) — no truncation from the patch passes. `PRD_FINALIZED.md` correctly absent (Step 8 skipped). No re-sweep was run after Step 9 because Step 9 touches only PRD prose — `implementation/` and both test directories are byte-unchanged since the green sweep, so `results.{1..8}.json` remain the valid evidence. `__pycache__` artifacts left by the sweep were removed so the tree contains only source.

## Pipeline complete — 2026-09-03T12:22:00.000Z

All 9 steps done. Final state: 85/85 tests passing in all 8 concurrent rounds, zero deletions, zero fixes, and a PRD completed against a full 20-module implementation scan.
