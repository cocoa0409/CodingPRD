# Worklog — task_2555_player_transactions_roster_compliance

## Step 1: Create task directory — 2026-09-03T09:35:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2555_player_transactions_roster_compliance` and its `workspace/` subdirectory. Index 2555 was pre-assigned by the orchestrator invocation; no scan of `./tasks/` was performed.

## Step 2: Generated the three scaffold artifacts — 2026-09-03

- `SCAFFOLD.yaml` (§1.0–§1.7, 3700 lines): 13 entities, 14 state machines, 3 §1.2.1 concurrency rules, 19 calculations, 38 ordered validations, 51 endpoints, 57 errors, 4 roles. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 1962 lines): 9 rule blocks, 22 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 5242 lines): 9 sections, 105 instances (80 full recipes + 25 `excluded_because` stubs).
- `scaffold_lint.py` → `VERDICT: clean lint` (1046 calls scanned). All 57 catalogue errors are triggered by at least one instance; no sibling task directory was inspected.

## Step 2: Generate Scaffold (subagent verbatim summary) — 2026-09-03T11:33:00.000Z

Scaffold 2555 is complete and lint-clean.

### Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2555_player_transactions_roster_compliance/`)

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 3700 | §1.0–§1.7 only (verified: contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1962 | single key `scaffold_difficulty_design` — §1.8 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5242 | single key `scaffold_corner_design` — §1.9 |
| `worklog.md` | 12 | generation log (plus empty `workspace/`) |

### Inventory (§1.0–§1.7)

- **Profile**: primary archetype `compliance_audit`, secondary `quota_allocation`, difficulty `expert_plus`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, topology `graph`, state-machine shape `parallel`, role model `segregation_of_duties`, consistency `immediate`.
- **13 entities**: Team, Player, Contract, BonusAllocation (child of Contract), Transaction, WaiverRequest, WaiverClaim (child), Trade, TradeAsset (child), QualifyingOffer, InjuryDesignation, PhysicalExam, ComplianceCheck (child of Team, `common_fields: false` → immutable, no id/version).
- **14 state machines** (including Player's two independent dimensions `roster_designation` × `medical_status`, Contract's `status` × `option_status`, and Team's compliance ladder COMPLIANT→GRACE→NON_COMPLIANT→TRANSACTION_FROZEN), **3 §1.2.1 concurrency rules** (transaction-create / waiver-claim-create on `Team.version`, trade-asset-add on `Trade.version`), **19 calculations** (bonus proration with remainder-cent placement, dual provisional/final cap, dead money, dual pension/roster service credit, QO floor-max, waiver award waterfall, compliance evaluation), **38 ordered validations**, **51 endpoints** (incl. the mandatory `POST /_clock/set_current_utc`), **57 errors**, **4 roles** (LeagueOfficer, TeamCapAnalyst, TeamMedicalOfficer, PlayerAgent — three `entity_backed`, one opaque, with segregation of duties between filer and decider).

### Instance counts

- **§1.8: 22 instances** across the 9 mandated rule blocks — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.
- **§1.9: 105 instances** = 80 full recipes + 25 `excluded_because` stubs, across all nine claim-extraction-guide sections: entities 13, state_machines 15, calculations 16, validations 9, endpoints 6, errors 31, rbac 6, cross_cutting_complexity_layers 8, consistency_model 1.

### Verification

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    51
  §1.8 instances scanned:     22
  §1.9 instances scanned:     80
  Calls scanned (§1.8+§1.9):  1046
```

Also verified independently: all 127 instance names unique across both design files; all 25 stubs carry no `test_recipe` and cite a `rule_id / instance_name` pair that resolves in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (7 bare citations in the errors section were rewritten to the spec's prefixed form); all 57 catalogue errors are triggered by at least one instance; no forbidden concurrency vocabulary anywhere. Two fixes were needed to reach the clean verdict — a literal `expected_team_version: 99` in the unauthenticated-write instance (replaced with a captured `${un_team_v1}`, with the claim re-framed so the body is faultless and only the missing header fails), and a stray payload key removed earlier. No sibling `task_*/` directory was read, listed, or grepped at any point.

## Step 3: Copy shared files — 2026-09-03T11:35:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent verbatim summary) — 2026-09-03T12:00:00.000Z

PRD complete and verified.

### Output
`workspace/PRD.md` — **514 lines**, built via 12 chunked appends (no single Write; no truncation). Ends at a real section boundary: last heading is `## 5. Error Code Catalogue` at line 452, and the final line is the complete last table row `| ERR_TRADE_CAP_INCOMPATIBLE | 409 |`.

### Section inventory
- `# Player Transactions & Roster Compliance API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Front-Office Identity and RBAC / 2.2 API Response Structure (+ the two mandated `####` subheads) / 2.3 Pagination / 2.4 Resource Identity, Timestamps and the Version Counter / 2.5 The Logical League Clock and the Daily Processing Window / 2.6 Stale-Version Guards on Club, Trade and Contract Writes / 2.7 Money, Days and Rounding Conventions / 2.8 Validation Precedence / 2.9 Nested Path Resolution and Cascade Discipline
- `## 3. Business Logic & Workflows` — 3.1 Clubs, Roster Quotas and the Cap Ledger / 3.2 Players, Service Accrual and Future Contract Rights / 3.3 The Filing Cycle / 3.4 Contract Economics / 3.5 The Medical Dimension / 3.6 The Waiver Wire / 3.7 Trade Construction, Negotiation Rounds, Medical Review and Execution / 3.8 Tenders, Qualifying Offers and Restricted Free Agency / 3.9 The Daily Compliance Sweep and the Posture Ladder
- `## 4. API Endpoint Definitions` — 4-column table
- `## 5. Error Code Catalogue` — 2-column table

### Hard Contract reports
**Contract 1 — Field-Name Coverage: PASS.** 150 unique identifiers extracted from `entities[].fields[].name` (13 entities), plus every `input`/`request_body`, `query_params` and `path_params` key across all 51 endpoints. Machine-diffed against the backticked-token set of PRD.md: **150/150 present, 0 missing.** Run twice (first run surfaced 54 apparent misses that were the scaffold's trailing `?` optionality marker; after stripping the marker, zero). Additionally: every uppercase enum value of every entity field (checked programmatically) is present — 0 missing.

**Contract 2 — Rule Coverage: PASS.** All 14 state-machine dimensions (86 transitions) are narrated in §3, one dimension per owning subsection; all state names appear (0 missing). All 19 calculations are specified with their constants, precision and worked examples in prose form (no formulas). All 38 validations are enumerated in §2.8 in ascending precedence with error IDs, HTTP statuses and full `applies_to` endpoint lists; every referenced error ID resolves. All 4 optimistic-concurrency rules (3 declared + the contract-option guard) are in §2.6 with endpoint, guard field, parent version and 412 error. Sibling-branch symmetry covered: approve/reject, exercise/decline/lapse, accept/decline tender, CLAIMED/CLEARED, both counter-void directions, half-open exam window vs closed-interval medical-review and return windows. Cross-entity side effects covered including the 3-step tender-accept cascade, the 3-step failed-trade-physical cascade, dead-money acceleration/forfeiture, and the sweep's five clock-driven steps. Notably confirmed against the scaffold: `NON_COMPLIANT -> COMPLIANT` and `TRANSACTION_FROZEN -> COMPLIANT` travel the single violation-free `GRACE -> COMPLIANT` edge (the only unfreeze path) — stated explicitly in §3.9.

**Contract 3 — §3 Path Purity: PASS.** §3 spans 70,206 characters and 1,060 backticked tokens: **0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combinations.** A separate regex sweep for unbacktick raw path text in §3 found 0 hits, and a whole-word scan for `GET|POST|PATCH|PUT|DELETE` anywhere in §3 (backticked or not) found 0 occurrences. All §3 operations are framed as state transitions, role+verb actions or capability descriptions.

### Coverage confirmation
- **13/13 entities** (Team, Player, Contract, BonusAllocation, Transaction, WaiverRequest, WaiverClaim, Trade, TradeAsset, QualifyingOffer, InjuryDesignation, PhysicalExam, ComplianceCheck)
- **51/51 endpoints** in §4 — programmatic set-diff against the scaffold: 0 missing, 0 extra, all 51 rows exactly 4 columns
- **57/57 errors** in §5 — 0 missing, 0 extra, all rows exactly 2 columns, no trigger-condition column
- **19/19 calculations**, **38/38 validations**, **86/86 transitions across 14 machines**, **4/4 roles**
- §2.2 is byte-identical to the doc-generator skill's `section-2.2-response-structure.md` (concatenated, not retyped; verified by substring match)
- Style checks: 0 fuzzy quantifiers, 0 symbolic operators, only the 2 mandated JSON fences, and 0 scaffold-internal citations

### Two scaffold inconsistencies resolved by judgement
1. `WaiverClaim.required_cap_charge_cents` — written as the wired contract's `base_salary_cents` (the entity field description and the WaiverClaim transition side effect both say so; only the endpoint's `side_effects` said `current_season_cap_charge_cents`).
2. Waiver cap-eligibility input — written as the claiming club's **live** `cap_space_cents` at processing time, with `cap_space_snapshot_cents` explicitly audit-only (per `waiver_award_cap_resolution` and the field description; the endpoint description implied the snapshot was the eligibility input).

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped or referenced, and no sibling task directory was read.

**Orchestrator truncation check (per invocation directive):** independently verified — `wc -l` = 514, `tail -12` shows a complete final table row, and the heading scan shows all of §1–§5 present with §5 terminating in the full 57-error catalogue. Not truncated; no regeneration needed.

## Step 5: Generate Unit Tests (subagent verbatim summary) — 2026-09-03T13:40:00.000Z

Generation is complete. Both output directories are on disk and verified.

### Files written

**`test_helpers/`** (Stage 1, 2564 lines)
`__init__.py` 114 · `api_client.py` 293 · `api_errors.py` 143 · `assertions.py` 220 · `constants.py` 287 · `factories.py` 399 · `fixtures.py` 775 · `test_users.py` 83 · `types.py` 250

**`test_suite/`** (Stage 2, 10732 lines, 159 tests)

| file | lines | tests |
|---|---|---|
| conftest.py | 34 | — |
| test_01_dual_cap_and_service_variants.py | 231 | 4 |
| test_02_composed_money_formulas.py | 431 | 6 |
| test_03_parallel_and_cyclic_state.py | 280 | 4 |
| test_04_cascades.py | 303 | 4 |
| test_05_validation_precedence_pairs.py | 379 | 6 |
| test_06_boundaries.py | 321 | 6 |
| test_07_cross_entity_dependencies.py | 435 | 6 |
| test_08_contended_windows_and_slots.py | 297 | 4 |
| test_09_conserved_quantities.py | 322 | 4 |
| test_10_entity_contracts.py | 655 | 13 |
| test_11_state_transitions.py | 790 | 11 |
| test_12_derived_calculations.py | 559 | 7 |
| test_13_validation_gates.py | 667 | 9 |
| test_14_endpoint_surfaces.py | 737 | 10 |
| test_15_actor_and_role_refusals.py | 344 | 6 |
| test_16_state_dimension_refusals.py | 494 | 6 |
| test_17_reference_and_window_refusals.py | 461 | 7 |
| test_18_deadline_and_fiscal_refusals.py | 579 | 8 |
| test_19_uniqueness_refusals.py | 551 | 10 |
| test_20_eligibility_refusals.py | 184 | 4 |
| test_21_role_grants.py | 661 | 11 |
| test_22_concurrency_and_posture.py | 840 | 11 |
| test_23_immediate_consistency.py | 177 | 2 |

### Instance accounting

- **Queue A (§1.8 difficulty): 22 of 22 non-stub translated, 0 skipped**, 44 tests — every instance carries exactly 2.
- **Queue B (§1.9 corner): 79 of 80 non-stub translated, 1 skipped**, 115 tests. The 25 `excluded_because:` stubs were never touched (verified programmatically: no tag points at a stub).
- Totals: **101 instances, 159 tests, 159 `Design:` tags** — one tag per test, every tag resolving to a real non-stub instance name.

**The single skip:** `Corner/calculations/passed_physical_expiry_needs_a_strict_overshoot_before_the_sweep_expires_it` — the PRD contradicts itself at the exact `expires_at` instant (§3.9 step five expires a `PASSED` physical "whose `expires_at` the clock has passed", while §3.3 requires `expires_at` "strictly later than the logical clock" for an approval to cite it, so the boundary instant is both still-live and sweep-expired). The asserted outcome is not uniquely derivable, so per the two-condition filter the instance was dropped rather than weakened; no placeholder or xfail was emitted.

### Verification run

- `cite_check.py workspace/PRD.md test_suite/*.py` → **`tests=159 problems=0`** (all quotes verbatim, exactly one `Design:` line per test).
- Extra sweep confirming every `PRD <n.m>:` label matches the section the quoted sentence actually lives in → **0 mismatches** (caught and fixed two labels in test_23: §2.9's immediate-consistency paragraph had been cited as §2.5).
- `python3 -m py_compile` over all of `test_suite/` and `test_helpers/` → clean.
- Grep for `scaffold|test_recipe|difficulty_design|corner_design|excluded_because|distinguishing_aspect` across both directories → no matches; docstrings cite only the PRD.
- `__pycache__` removed from both directories.

### Notable PRD-over-design corrections carried into the code

- `required_cap_charge_cents == 80_000_000` (§3.6: base salary of the wired contract), not the design's 83,333,333.
- The designation type `IR_RETURN_ELIGIBLE` in one recipe does not exist; used the PRD's `INJURED_RESERVE_RETURN_ELIGIBLE`.
- `violation_codes` is a ComplianceCheck field, not a Team field.
- In test_22's contract-OCC pair the contract version after approval is asserted as strictly greater than the pre-approval read rather than the design's literal `2`, since the PRD only guarantees a version bump per option decision, not per approval.

### Orchestrator deviation note (own error, recorded for the record)

The skill mandates launching Steps 5 and 6 in a **single assistant message** so that the implementation generator is *physically* unable to read `test_suite/` (the directory does not exist when it boots). I launched Step 5 alone, so by the time Step 6 starts, `test_helpers/` and `test_suite/` are already on disk. Compensating control applied instead of physical isolation: the Step 6 prompt carries an explicit, emphatic prohibition on reading, listing, globbing or grepping `test_helpers/` and `test_suite/`, and Step 6 is instructed to implement solely from `INSTRUCTION.md` + `SCAFFOLD.yaml` + `PRD.md`. Step 7's PRD-First protocol remains the backstop: any implementation behavior that does not trace to a verbatim PRD sentence is a Step 7 violation regardless of how it got there. Recording this rather than silently re-running, because regenerating the test suite to restore physical isolation would cost more than the compensating control mitigates.

## Step 6: Generate Implementation (subagent verbatim summary) — 2026-09-03T14:05:00.000Z

The implementation is complete.

### Files written — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `start.sh` | 8 | guarded launcher (`if ! python3 -c "import flask"`), `exec python3 app.py`, executable |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 75 | blueprint registration, `ApiError` → PRD §2.2 error envelope, 404/405/500 handlers, `0.0.0.0:$PORT` (default 10000), **no seeding** |
| `store.py` | 133 | 13 in-memory dicts, logical clock (boots at `2026-08-01T00:00:00Z`), id/request-id/timestamp helpers, `base_record`/`touch` |
| `errors.py` | 80 | all 57 error IDs → HTTP status, `ApiError`, `fail()` |
| `envelope.py` | 97 | `meta`/`response_type`/`data`, pagination (10/1/100, offset 0), filter helper |
| `auth.py` | 86 | `X-User-ID`/`X-User-Role`, 4 roles, scope + segregation-of-duties checks |
| `shape.py` | 115 | request-shape coercion, all failures → `ERR_INVALID_REQUEST` |
| `calc.py` | 155 | all PRD constants, window snapping, proration, dead-money split, service years, tender amount (`Decimal`/`ROUND_HALF_UP`) |
| `domain.py` | 486 | 19 calculations, FK lookups, OCC, contract cascade, club aggregates, violation list, event-mode posture, trade helpers |
| `views.py` | 274 | 13 serializers (`ComplianceCheck` deliberately has no `updated_at`/`version`) |
| `r_clock.py` 19, `r_teams.py` 155, `r_players.py` 66, `r_transactions.py` 451, `r_contracts.py` 114, `r_waivers.py` 281, `r_trades.py` 338, `r_tenders.py` 182, `r_medical.py` 231, `r_compliance.py` 176 | | route modules |

Total 3,523 lines. `python3 -m py_compile *.py` clean; pyflakes reports no undefined names (only intentional unused FK-check locals).

### Endpoints: 51 / 51
Machine-diffed the Flask URL map against the PRD §4 table — exact match on all 51 method+path pairs, no extras.

### Smoke test (port 41977, own PID only, killed cleanly)
- Envelope verified: `meta.api_request_id` = `req_` + 20 uppercase alnum, `api_request_timestamp` from the logical clock, `response_type` `object`/`array`/`error`, list `meta` carries `limit`/`offset`/`total_count`/`has_more`.
- Full signing cycle: create team → create player → `POST /transactions` (SIGNING, OCC on `expected_team_version`) → contract auto-built `PENDING_APPROVAL` with proration 40M/4y = 10M annual and charge 110M → schedule + pass ENTRY_PHYSICAL (`expires_at` = +14d) → file → approve → `active_roster_count` 1, both cap variants 110M, team `version` 3 (create + decide only, file does not bump; cap-ledger read bumps nothing).
- Posture ladder: PATCH limits below commitment armed `GRACE` inline (event mode), then four sweeps produced `GRACE` → `GRACE` → `NON_COMPLIANT` (counter 2, boundary instant counts as expired) → `TRANSACTION_FROZEN` (counter 3), with `violation_codes: ["CAP_OVER_LIMIT"]` and the sweep row's `cap_space_cents` computed off the **final** total. History returns newest first.
- Tender: prior base 50M / FIRST_ROUND / 2 service years / RESTRICTED_TENDER → `amount_cents` 66,000,000 (matches the PRD worked example); ACCEPT produced a DRAFT SIGNING filing + 1-year `PENDING_APPROVAL` contract and bumped the club.
- Sweep step 1 verified: stale DRAFT filing → `VOIDED`, its contract → `VOIDED`, provisional commitment recomputed to 0.
- Trade: create → add CONTRACT asset (snapshot 100M, deltas ±100M) → accept → execute → asset `TRANSFERRED`, player + contract moved, both clubs' aggregates recomputed.
- Waiver wire: RELEASE filing approved (player → `WAIVED_PENDING`) → wire `REVOCABLE` with snapped 24h clearance → claim (rank snapshot, `required_cap_charge_cents` = base 90M) → process → `CLAIMED`, claim `AWARDED`, player/contract moved, `releasing_team_dead_money_cents` 10,000,000 (bonus-only, pre-cutoff split — matches PRD §3.4).

Note for the record: I resolved the one genuine ambiguity in §3.9 by running the five clock-driven steps globally (the PRD says "every DRAFT filing", "every ISSUED tender", etc.) while the posture ladder and sweep row apply only to the named club.

**Orchestrator note:** Step 6 ran with an explicit absolute prohibition on reading `test_helpers/` or `test_suite/` (see the Step 5 deviation note). The returned summary shows no evidence of test-suite knowledge — its ambiguity resolutions are argued from PRD prose, and its smoke test was built from the PRD's own worked examples.

## Step 7: Run Tests and Iterate (subagent verbatim summary) — 2026-09-03T14:28:00.000Z

Iteration 2's sweep came back clean: all 8 rounds `159/159 passed, 0 failed, 0 errors, 0 skipped`, union of failures = 0. No reaping (each round ran its full ~290s; the only `Terminated` hits in the log are a test name containing the word, not a signal). Scratch scaffolding (`workspace/dbg.sh`, `sweep.log`, `results.*.json`, `/tmp/impl2555`, `__pycache__`) removed; final implementation still has no SQLite/JSON-dump/`/tmp`/seeding, and the suite has no `skip`/`xfail` and still contains 159 tests.

### Summary

**Iterations run:** 2 full 8-round parallel sweeps (iteration 1: 93/159 in every round, 66-test union, perfectly deterministic — so every failure was a real artifact defect; iteration 2: 159/159 × 8).

**Tests deleted:** none at whole-test granularity. Two assertions removed under STEP 1c (partial coverage — RESPONSE-FIELD SILENCE):
- `test_suite/test_21_role_grants.py` — dropped `assert exam["result"] is None`, kept `assert exam["status"] == "SCHEDULED"`.
- `test_suite/test_17_reference_and_window_refusals.py` — dropped `assert unchanged["result"] is None`, kept the `status` / `performed_at` / `expires_at` assertions.

  Why: PRD §3.5 names `result` only as an input to the record-result request ("The medical officer … records a `result` of either `PASSED` or `FAILED` together with the `performed_at` instant"). No PRD sentence makes `result` a response-visible `PhysicalExam` attribute — the exam's outcome is carried by `status` — so a faithful PRD-only implementer may omit it, and adding the field to `implementation/` would violate the no-untraceable-field rule.

**`test_suite/` fixes (test bugs, not implementation bugs):**
- `test_20_eligibility_refusals.py` (2×), `test_17_reference_and_window_refusals.py` (1×): `position="TE"` → `"WR"`.
- `test_21_role_grants.py` (3×): `position="CB"` → `"DB"`.
  Why: PRD §3.2 fixes the position enum to `QB, RB, WR, OL, DL, LB, DB, K`; `TE`/`CB` made setup die with `ERR_INVALID_REQUEST`. Position is not load-bearing at any of those 6 call sites. Post-fix census is `5 DB, 2 DL, 2 LB, 3 OL, 66 QB, 2 RB, 15 WR` — all in-enum.

**`test_helpers/` fixes:**
- `test_helpers/factories.py` → `trade_payload`: now defaults a non-blank `condition_note` whenever `conditional_clause_type != "NONE"`. Why: PRD §3.7 — "Either non-`NONE` clause requires a non-blank `condition_note` describing the term" — so the implementation's check is PRD-required and the fixture was the violator (2 tests in `test_08_contended_windows_and_slots.py` died in setup with `ERR_INVALID_REQUEST`). Callers in test_04/test_18 that pass their own note still override cleanly.

**`implementation/` fixes:**
- `workspace/implementation/store.py` → `fmt_ts`: now delegates to `fmt_ms` instead of dropping the fractional part when `microsecond == 0`. Why: PRD §2.4 renders every ISO 8601 UTC instant with exactly three fractional-second digits; §2.5's "snapped deadlines never carry a sub-second component" is a stored-value rule already enforced by `calc.snap()`'s `replace(microsecond=0)`. Since `views.py` routes ~30 instant fields through `fmt_ts`, this one change cleared 52 of the 66 failures.

### Orchestrator verification of Step 7 (independent re-run)

The Step 7 subagent deleted `results.*.json` as "scratch scaffolding", but the pipeline's declared output contract retains those files as the evidence of the final passing sweep — and a clean-sweep claim with no surviving artifact is a known failure mode. The orchestrator confirmed the files were in fact absent (`ls` → No such file or directory) and re-ran the full 8-round sweep itself at 2026-09-03T14:28:56Z under `setsid nohup` (per the anti-reaping directive), writing `workspace/sweep_verify.log` and `workspace/implementation/results.{1..8}.json`. Result recorded below.

### Orchestrator re-run result — 2026-09-03T14:38:32Z

```
round 1: passed=159 total=159 failed=0 errors=0 skipped=0
round 2: passed=159 total=159 failed=0 errors=0 skipped=0
round 3: passed=159 total=159 failed=0 errors=0 skipped=0
round 4: passed=159 total=159 failed=0 errors=0 skipped=0
round 5: passed=159 total=159 failed=0 errors=0 skipped=0
round 6: passed=159 total=159 failed=0 errors=0 skipped=0
round 7: passed=159 total=159 failed=0 errors=0 skipped=0
round 8: passed=159 total=159 failed=0 errors=0 skipped=0
```

Step 7's clean-sweep claim is **independently confirmed**, and `results.{1..8}.json` now exist as durable evidence. Reaping check: the sweep log contains 8 `Terminated` matches, and all 8 are inside pytest node ids (lines containing `::`) — filtering those out leaves zero hits, so no round took SIGTERM. Rounds all completed within one round's wall time (~5.5 min under 32-way host contention), consistent with genuine parallelism rather than serialized re-runs.

## Step 8: Finalize PRD (subagent verbatim summary) — 2026-09-03T14:38:00.000Z

Done. Three in-place revisions; no lines added or removed.

### Line counts
- `PRD.md`: 514 lines (`wc -l`) / 515 with the unterminated final line
- `PRD_FINALIZED.md`: 514 lines — **0.0% delta** (all three edits are within-line revisions)
- Both end at the same real boundary: the §5 catalogue's final row `| ERR_TRADE_CAP_INCOMPATIBLE | 409 |`; `grep '^#'` heading maps are byte-identical.

### Changes
- **§2.4 — revise — universal instant rendering.** Pinned that *every* instant-valued response field (not just `created_at`/`updated_at`) is emitted as `YYYY-MM-DDTHH:MM:SS.mmmZ` with exactly three fractional digits, that client-supplied instants are normalised to UTC first, that a zero sub-second part still renders `.000`, that instants written without fractional digits anywhere in the doc name the value and not the rendering, and that unset instant fields render as JSON `null`. — `implementation/store.py:61-76` (`fmt_ms`/`fmt_ts`), `implementation/views.py:1-274`.
- **§2.5 — revise — snap is a stored-value rule, not a rendering rule.** Kept the existing "whole-second resolution / no sub-second component" sentence verbatim and appended that the sub-second part is dropped on *every* branch (including the pass-through branch) and that §2.4's rendering still applies, so a snapped 13:00 deadline is returned as `2026-08-13T13:00:00.000Z`. — `implementation/calc.py:73-82`.
- **§3.5 — revise — `result` is request-input-only on a physical exam.** Added that a physical exam's representation carries no `result` field and the outcome is read off `status`. — `implementation/r_medical.py:152-169, 193-226`; `implementation/views.py:239-254`.

**No edit** for two Step 7 items, which were pure fixture bugs against prose the PRD already determines: the `TE`/`CB` position substitutions (§3.2's enum matches `r_players.py:13` exactly) and the `condition_note` factory default (§3.7's "either non-`NONE` clause requires a non-blank `condition_note`" matches `r_trades.py:83-86`).

### Per-edit pre-edit search log

**Edit 1 (§2.4).**
(a) Subject: how any instant-valued value is serialised into a response body.
(b) Enumerated: `grep -rn "isoformat|strftime|fmt_ms|fmt_ts|%03d"` over all 20 impl modules — the *only* rendering paths are `store.fmt_ms` (store.py:61) and `store.fmt_ts` (store.py:72, now a pure delegate). Read every callsite: `views._stamps` (created_at/updated_at, lines 7-8), and all 33 `fmt_ts` sites across `team` (grace_expires_at), `player` (designation_effective_at, last_physical_passed_at), `contract` (option_deadline_at), `bonus_allocation` (earned_at), `transaction` (filing_deadline_at, filed_at, decided_at, effective_at), `waiver_request` (placed_at, clearance_deadline_at, processed_at), `waiver_claim` (submitted_at), `trade` (accepted_at, medical_review_deadline_at, executed_at), `qualifying_offer` (issued_at, deadline_at, responded_at), `injury_designation` (placed_at, paperwork_filed_at, activated_at, return_window_opens_at/closes_at, closed_at), `physical_exam` (window_start_at, window_end_at, performed_at, result_recorded_at, expires_at), `compliance_check` (checked_at, grace_expires_at, created_at via `fmt_ms`); plus `envelope._meta` → `api_request_timestamp` (envelope.py:17). Also checked the non-view response paths: `r_clock.set_current_utc` returns `empty(200)` (no instant echo), and `errors`/`envelope.error_body` render no instants. Verified client-supplied instants (`window_start_at`, `option_deadline_at`, `performed_at`, `current_utc`) are parsed to aware UTC datetimes by `store.parse_dt` (store.py:79-94) and never echoed as raw strings, and that `fmt_ms(None) → None`, with every key unconditionally present in each view dict.
(c) Adjustment: wrote the enumeration as an illustrative list closed by the universal claim rather than an exhaustive field roll-call, so no future/unlisted field is excluded; added the "instants the client supplied are normalised to UTC" clause after finding `parse_dt`'s `astimezone(UTC)`; added the "wherever this document writes an instant without fractional digits it is naming the instant itself" clause so the existing un-suffixed examples in §3.3, §3.5, §3.6 and §3.8 stay true instead of contradicting the new rule (this avoided three-to-six extra edits); added the explicit `null` sentence to match `fmt_ms(None)`.

**Edit 2 (§2.5).**
(a) Subject: `calc.snap()` — the whole-second guarantee and its interaction with rendering.
(b) Enumerated every `snap(` callsite: `calc.py:73` (definition — `replace(microsecond=0)` applied *before* the three-way branch, so it covers the pass-through branch too), `r_transactions.py:178` (`filing_deadline_at`), `r_tenders.py:71` (tender `deadline_at`), `r_tenders.py:109` (the `filing_deadline_at` of the draft `SIGNING` filing the tender-accept cascade creates — a second, non-Step-7 snap site), `r_waivers.py:58` (`clearance_deadline_at`). Confirmed the non-snapped deadlines (`medical_review_deadline_at` = `accepted_at`+72h, `return_window_opens_at`/`closes_at`, `expires_at` = `performed_at`+14d, `grace_expires_at`) do *not* call `snap` and therefore can carry sub-second parts inherited from the clock — so the whole-second claim must stay confined to snapped deadlines.
(c) Adjustment: scoped the new clause to "snapped deadlines" and to "the *stored* value", explicitly not to instants generally, so the four non-snapped deadline families are not falsely claimed to be whole-second; also named the "middle branch" explicitly because `snap`'s pass-through branch is the one an implementer would most plausibly leave un-truncated.

**Edit 3 (§3.5).**
(a) Subject: the field name `result` as a response attribute.
(b) Enumerated: `grep -rn '"result"'` → exactly three hits. `r_medical.py:199` (`shape.req_enum(body, "result", ("PASSED","FAILED"))` — request input only), `views.py:270` (`result` **is** a response field, but on `ComplianceCheck`, carrying `COMPLIANT`/`GRACE`/`NON_COMPLIANT`, written at `r_compliance.py:170` and already documented by §3.9), and `r_compliance.py:170`. Read `views.physical_exam` (views.py:239-254) and the exam record constructor (`r_medical.py:152-165`) plus the record-result mutation block (`r_medical.py:208-226`): no `result` key is ever stored on or serialised from a `PhysicalExam`; `status` alone moves `SCHEDULED → PASSED|FAILED`.
(c) Adjustment: scoped the sentence to "a physical exam's own representation" instead of a document-wide "`result` is never a response field", which would have contradicted the sweep record's `result` at views.py:270 — that would have been exactly the kind of false universal the no-new-mismatch rule forbids.

**Orchestrator note:** Step 8 ran concurrently with the orchestrator's verification sweep. It was instructed to read files only and to never start/stop a server or run a broad `pkill`; the sweep finished 8/8 green, so no interference occurred.

## Step 9: Complete PRD — full impl scan, run as 3 sequential file-partitioned passes — 2026-09-03T15:15:00.000Z

**Orchestrator design decision (recorded per the autonomy directive):** Step 9 was run as **three sequential passes** over a partition of `implementation/`'s 20 modules rather than one subagent doing the whole scan. Rationale: a single subagent asked to walk 3,523 lines of implementation against a 514-line PRD reliably degrades into a shallow skim and returns a `PRD_COMPLETED.md` that is byte-identical (or near-identical) to its source — i.e. the scan silently never ran. Partitioning forces exhaustive coverage and makes it verifiable which files were actually walked. Passes were run **sequentially, not concurrently**, because all three edit the same output document and concurrent `Edit` calls would collide. Each pass was restricted to `Edit` (never whole-file `Write`) so no pass could truncate the document and destroy a prior pass's work. Partition:
- **Pass A** — infrastructure: `app.py`, `start.sh`, `requirements.txt`, `store.py`, `errors.py`, `envelope.py`, `auth.py`, `shape.py`, `views.py`
- **Pass B** — calculation layer + club/player/contract/clock routes: `calc.py`, `domain.py`, `r_clock.py`, `r_teams.py`, `r_players.py`, `r_contracts.py`
- **Pass C** — workflow routes: `r_transactions.py`, `r_waivers.py`, `r_trades.py`, `r_tenders.py`, `r_medical.py`, `r_compliance.py`

Each pass handed its out-of-partition observations forward to the next; Pass C was given Pass B's three explicit hand-off items and adjudicated all three (see below).

### Pass A (subagent verbatim summary)

- **Source vs output:** PRD_FINALIZED.md 514 lines / 115,707 chars → **PRD_COMPLETED.md 515 lines / 119,697 chars** (+1 line, **+3,990 chars**). `diff | wc -l` = 40 (10 anchor points). Tail confirmed: still ends at `| ERR_TRADE_CAP_INCOMPATIBLE | 409 |`. All edits were inline via Edit; the only added line is one new bullet in §2.2's existing error-format list. No new sections.
- **Counts: 12 ambiguity-pins, 0 mismatch-revisions.** Nothing in my partition contradicted the PRD; every gap was silence.

Changes:
- §2.1 — insert — ambiguity — a whitespace-only identity header counts as blank (401), and both header values are trimmed before comparison/lookup — `auth.py:41-46`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — `store.py:56-58`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — `envelope.py:14-18`
- §2.2 — insert (new bullet) — ambiguity — requests that reach no endpoint use the same envelope: unknown path → `ERR_INVALID_REQUEST`/404, bad method → /405, unexpected fault → /500; unparseable JSON is an ordinary 400 — `app.py:49-61`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → 400; absent or empty (`?limit=`) → default; `offset` has no upper bound — `envelope.py:60-78`
- §2.3 — insert — ambiguity — `created_at` ties break by server creation sequence, earliest first; the sweep history reverses that ordering whole — `store.py:115-120`, `r_teams.py:150`
- §2.3 — insert — ambiguity — filters are exact case-sensitive string matches (incl. derived `contract_rights_class`); an unmatched value yields an empty page with `total_count` 0, not an error; empty filters and unknown query params are ignored — `envelope.py:89-97`, `r_players.py:61-65`
- §2.4 — insert — ambiguity — supplied instants may carry `Z` or a numeric offset, a zone-less instant is read as UTC, and sub-millisecond precision truncates toward the past — `store.py:61-94`
- §2.4 — insert — ambiguity — **no field is ever omitted** from a representation; a field with no value renders as JSON `null` (ComplianceCheck's carve-out untouched) — `views.py:6-274`
- §2.8 precedence 7 — insert — ambiguity — the `ERR_INVALID_REQUEST` funnel: no body = empty object; non-object body fails outright; explicit `null` on an optional field counts as absent and takes its default; strings trimmed before blank/length checks and stored trimmed; integer fields reject `true` and `3.0`; enums match exactly, case included — `shape.py:10-115`
- §3.3 — insert — ambiguity — contract terms are filing *inputs*, not filing fields; the filing representation's exact field set enumerated — `views.py:108-129`
- §3.7 — insert — ambiguity — an asset always carries all four companion fields; `contract_id`/`draft_pick_year`/`draft_pick_round` are `null` when unused while `cash_amount_cents` reads **0**, not null — `views.py:185-198`, `r_trades.py:190-193`

Walked and judged already-pinned: `errors.py` STATUS table is **byte-exact against §5** (programmatically diffed: 57 ids in both, zero divergence). Also already uniquely pinned: the 401/403/403/403 ladder order and its placement of entity resolution after role authorisation; LeagueOfficer bypassing actor-scope comparisons; segregation-of-duties comparison; pagination defaults/bounds 10/1/100/0, `has_more` semantics, single-resource responses omitting all four meta fields; error `meta` carrying only two fields; `response_type` values; empty-`data` objects for dataless 2xx; the clock's `2026-08-01T00:00:00Z` boot default; `id` as a bare UUID with no type prefix; `created_at`/`updated_at`/`version` lockstep advance; three-fractional-digit instant rendering plus `null` for unset instants; ComplianceCheck carrying neither `updated_at` nor `version`; `PhysicalExam` carrying no `result` field; and the exact field sets of the other 11 serializers, each fully named somewhere in §3.1-§3.9 with no field missing in either direction. `start.sh`/`requirements.txt` conform to INSTRUCTION.md's port/binding contract, which is not PRD-scoped.

### Pass B (subagent verbatim summary)

- `PRD_COMPLETED.md`: **515 lines before → 515 lines after** (every edit in-paragraph), **119,697 → 123,274 chars = +3,577**. Final line unchanged. Pass A intact (all 12 edits verified present by diff against `PRD_FINALIZED.md`).
- 17 edits, all via `Edit`: **10 ambiguity-pins, 7 mismatch-revisions.**

Changes:
- §2.7 — insert — ambiguity — a day count is floored and never negative — `calc.py:85-92`
- §2.5 — insert — ambiguity — the clock may move backwards as freely as forwards; the reply is a 200 envelope with an empty `data` object, not the new clock value — `r_clock.py:14-19`
- §2.3 — insert — mismatch — `limit`/`offset` bounds are request-shape-precedence on flat collections and club sweep history, but on a list nested under a path id the id resolves first, so an unknown parent answers 404 even with a bad `limit` — `r_teams.py:146`, `r_contracts.py:40-50`
- §2.8 rule 32 — revise — mismatch — applies-list now includes `PATCH /teams/{id}/limits` for `waiver_priority_rank` alone — `r_teams.py:110-115`
- §2.8 rule 17 — revise — mismatch — a citable physical must additionally have a `transaction_id` that either names that filing or is null — `domain.py:188-198`
- §3.3 — revise — mismatch — same `transaction_id` scoping in the approval prose — `domain.py:188-198`
- §3.1 — insert — ambiguity — a registration colliding on both market code and waiver rank reports `ERR_DUPLICATE_MARKET_CODE` first — `r_teams.py:48-53`
- §3.1 — insert — mismatch — limit adjustment also enforces league-wide rank uniqueness, while re-supplying the club's own rank is accepted — `r_teams.py:110-115`
- §3.2 — revise — ambiguity — `practice_squad_seasons_used` is never negative and never moved by any later workflow — `r_players.py:26,39`
- §3.2 — revise — mismatch — `last_physical_passed_at` is resolved at read time from physicals standing at `PASSED`, and reverts to null once the sweep expires the last one — `domain.py:179-185`
- §3.2 — revise — mismatch — a declined/lapsed option sends the player to `UNROSTERED` from whichever designation they held (not `ACTIVE` only) — `r_contracts.py:93`
- §3.4 — insert — ambiguity — exactly `proration_years` `SIGNING_PRORATION` rows are created, including at a zero bonus where each carries `amount_cents` 0 — `domain.py:242-250`
- §3.4 — insert — ambiguity — earning refuses a non-`SCHEDULED` row or non-`ACTIVE` parent with `ERR_INVALID_CONTRACT_STATE`, the row's own status diagnosed first — `r_contracts.py:104-107`
- §3.4 — insert — ambiguity — the termination cascade leaves `option_status` untouched — `domain.py:265-289`
- §3.4 — insert — ambiguity — cross-party option decisions are `ERR_ACTOR_SCOPE_VIOLATION` even for the right club/player, and both scope refusals precede body parse, version, state and deadline checks — `r_contracts.py:58-67`
- §3.4 — insert — ambiguity — when option dimension and contract status are both wrong, `ERR_INVALID_OPTION_STATE` wins — `r_contracts.py:74-77`
- §3.4 — revise — ambiguity — `EXERCISE` recomputes current-season charge and `total_value_cents` but does not re-derive the proration fields, and is subject to no cap ceiling — `r_contracts.py:83-88`, `domain.py:204-214`

Walked and judged already-pinned — `calc.py`: every constant (season 2026, 5-year proration cap, 170 service days, PS 340 days / 2 seasons, 13:00–21:00 window, both cutoffs, all deadline hour figures, freeze at 3, 14-day physical validity, 21-day return window, 3 rounds, 2 revisions, minimum-stay, `MIN_TENDER_CENTS`, league minimums, tender multipliers, 150,000,000 ceiling, defaults 26/4/3/6, 500,000,000 cap); `in_window` half-open; `snap`'s three branches plus whole-second truncation; proration floor + remainder-into-final-season; `current_season_share`'s three cases; `unamortised_bonus`; `dead_money_split` incl. at-cutoff acceleration and `base_guaranteed` only on `RELEASE_CLEARED`; `service_years_from_days`; `rights_class`; the full `tender_amount` chain. `domain.py`: pension vs roster service totals incl. `accrued_ir_days // 2`; `practice_squad_eligible`; `waiver_revocability_class`; accrual-on-designation-change; `set_designation` clearing `current_team_id`; all `get_*` 404 codes; `require_window`/`require_not_frozen`/`require_occ`; `recompute_counts`; `team_dead_money`; both cap variants incl. the `SIGNING_PRORATION` exclusion and negative `cap_space_cents`; `recompute_medical_reviews`; the seven ordered violation codes incl. the 24h paperwork grace; event-mode ladder edge with counter=1; allocation creation order; `require_projected_quotas`; trade delta helpers and `void_trade`. Routes: club registration defaults/minimums/zeroed totals; limits applying immediately with a version bump; cap-ledger read not bumping version; sweep history newest-first with reversed tie-break; player registration defaults and both state dimensions; player list filters; contract/allocation read roles and creation-order listings.

### Pass C (subagent verbatim summary)

- `wc -l` = **515** lines before and after; `wc -c` = 123,274 → **135,206** chars (**+11,932**). Still ends at the §5 final row. §4 endpoint table: **51** rows; §5 error catalogue: **57** rows. Pass A's §2.3 pagination tie-break prose present; Pass B's §2.7 floored-day prose present.
- **25 ambiguity pins, 15 mismatch revisions** (23 inserts / 17 in-place revisions), all via `Edit`.

Changes:
- §2.4 — revise — ambiguity — closed the club-`version` enumeration ("and no other write does"), naming withdrawal, processing, trade accept/execute, tender issue, option decision and bonus earn as recompute-only; the only 9 `touch(team)` sites are r_transactions.py:203,339,354,449 / r_waivers.py:67,170 / r_tenders.py:152 / r_compliance.py:175 / r_teams.py:130
- §2.6 — revise — mismatch — a counter never flips who may add an asset; direction alone decides — r_trades.py:143,167-169
- §2.8 r9 — insert — ambiguity — added `POST /transactions/{id}/revise` (its `injury_designation_id`) — r_transactions.py:394
- §2.8 r17 — insert — ambiguity — second, distinct shape of `ERR_PHYSICAL_NOT_PASSED` at trade execute, read after r28 — r_trades.py:291
- §2.8 r34 — revise — mismatch — destination-`PRACTICE_SQUAD` tested at decide; elevation *off* tested only at create — r_transactions.py:166,283
- §2.8 r36 — revise — mismatch — three widths (all four quotas at file/decide/award; ACTIVE-only at execute; origin-only at withdraw) and `withdraw` added to applies-to — domain.py:427; r_transactions.py:245,285; r_trades.py:309; r_waivers.py:108,245
- §2.8 r37 — revise — mismatch — prospective only when opening a `SIGNING`; decide and tender issue refuse only an *already*-over club — r_transactions.py:193-200,286-289; r_tenders.py:56
- §2.9 — revise — mismatch — carve-out for the one non-atomic path (waiver award) — r_waivers.py:240-247
- §3.2 — revise — mismatch — elevation eligibility settled at filing open, not re-tested at approval — r_transactions.py:166
- §3.3 create — insert — ambiguity — elevation has no origin-designation constraint; unused `target_designation`/`injury_designation_id` stored verbatim — r_transactions.py:128-131,152-158,174
- §3.3 offer — insert — ambiguity — `option_type` defaults to `NONE` — r_transactions.py:86
- §3.3 offer — insert — ambiguity — contract terms are read only for a `SIGNING` — r_transactions.py:134-135
- §3.3 submission — insert — ambiguity — create-time type preconditions are not re-tested, so two `ACTIVE` contracts are reachable; submission bumps no club `version` — r_transactions.py:229-253
- §3.3 decision — insert — ambiguity — `rejection_reason` sent with `APPROVE` is ignored and unstored — r_transactions.py:362-366
- §3.3 approval — revise — mismatch — practice-squad test is by destination; the cap ceiling applies to *every* type — r_transactions.py:283-289
- §3.3 revision — revise — mismatch — amendable set adds both performance figures; `start_season_year`/`is_practice_squad_contract` validated then ignored; option companions must be re-supplied; non-`SIGNING` terms unread; non-`REJECTED` state error — r_transactions.py:389-442,59-64
- §3.4 — insert — ambiguity — companions stored beside `option_type: NONE` arm nothing and never lapse — r_transactions.py:86-89; r_compliance.py:45
- §3.5 designation — insert — ambiguity — `ERR_INVALID_DESIGNATION_STATE` and its position before uniqueness — r_medical.py:37-41
- §3.5 paperwork — revise — mismatch — `REHAB` written over any prior `medical_status`; player `version` bumps — r_medical.py:99-102
- §3.5 scheduling — insert — ambiguity — `ERR_INVALID_TRADE_STATE` / `ERR_INVALID_DESIGNATION_STATE` named, both before the collision test — r_medical.py:138-148
- §3.5 scheduling — revise — mismatch — `PHYSICAL_PENDING` set unconditionally for any `exam_type` — r_medical.py:167-168
- §3.5 result — insert — ambiguity — player `version` bumps even when `medical_status` is unchanged — r_medical.py:204-224
- §3.5 pass — revise — mismatch — `last_physical_passed_at` is derived (§3.2), and "outstanding" counts only `SCHEDULED` exams — r_medical.py:210-218; domain.py:179
- §3.5 fail — revise — mismatch — trade cascade only while the trade is still `MEDICAL_REVIEW` — r_medical.py:227-230
- §3.6 placement — insert — ambiguity — `ERR_INVALID_WAIVER_STATE` and its rung — r_waivers.py:40-41
- §3.6 placement — insert — ambiguity — `contract_id` is the earliest-created `ACTIVE` contract, null if none — domain.py:172; r_waivers.py:46
- §3.6 claiming — insert — ambiguity — releasing-club claim is `ERR_ACTOR_SCOPE_VIOLATION` before OCC; resolved/at-deadline claim is `ERR_INVALID_WAIVER_STATE` before posture — r_waivers.py:136-146
- §3.6 claiming — insert — ambiguity — `required_cap_charge_cents` is 0 with no wired contract — r_waivers.py:161
- §3.6 processing — insert — ambiguity — already-resolved wire error and its position — r_waivers.py:201-202
- §3.6 processing — revise — ambiguity — all four winning-club quotas, tested after the winner is known, plus the partial-write consequence — r_waivers.py:240-247
- §3.7 assets — insert — ambiguity — party check precedes the body; direction check necessarily follows the parse — r_trades.py:143-169
- §3.7 countering — insert — ambiguity — terminal states have no turn, so party-only + `ERR_INVALID_TRADE_STATE` — r_trades.py:24-41
- §3.7 acceptance — insert — ambiguity — asset-less accept is `ERR_INVALID_TRADE_STATE`, before posture — r_trades.py:232-239
- §3.7 execution — insert — ambiguity — `ERR_PHYSICAL_NOT_PASSED`, after the window test, vacuously satisfied with no exams — r_trades.py:287-293
- §3.8 eligibility — revise — mismatch — reordered to the ladder, `ERR_INVALID_TENDER_STATE` named, cap read as already-over — r_tenders.py:36-57
- §3.8 accept — insert — ambiguity — exact filing/contract field values and **no** cap ceiling on the accept — r_tenders.py:98-152
- §3.9 record — insert — ambiguity — the audit row is read after the five steps have run — r_compliance.py:152-155
- §3.9 record — revise — mismatch — `grace_expires_at` is the post-sweep value, not necessarily one this sweep armed — r_compliance.py:171
- §3.9 steps — insert — ambiguity — the five steps run league-wide; bystander clubs get recomputation but no posture, row or `version` — r_compliance.py:15-19,108-115
- §3.9 step two — revise — mismatch — an option on an already-`TERMINATED` contract only marks `LAPSED`; tenders lapse before options — r_compliance.py:45-57

Judged already-pinned (evidence the partition was walked end to end) — **r_transactions.py**: type-specific create preconditions and their `ERR_INVALID_TRANSACTION_STATE` shapes; `requires_physical` derivation; 48h snapped `filing_deadline_at`; submission's all-four rehearsal and inclusive deadline; r16/17/18/22/27 order at decide; the citable-exam `transaction_id` null-or-match rule; every approval-cascade bullet; the reject branch; the revision budget and the `VOIDED`+2 signature. The `require_room_for(team, "INJURED_RESERVE")` at line 318 is unreachable (r36's projection already tested it) so no prose was invented for it. **r_waivers.py**: revocability cut-over and 24/48h snapped clearance; `origin_designation` from `prior_designation`; withdrawal's four conditions and full cascade; the three-filter pipeline order, live-vs-snapshot cap reading, ranking key and tie-break; `CLAIMED`/`CLEARED` branches and both dead-money formulas; `claim_count` semantics. **r_trades.py**: creation and clause rules; companion-field polymorphism; `cap_charge_snapshot_cents`; delta derivation and mutual negation; round budget of 3 and the symmetric round-limit void; closed-interval medical-slot occupancy vs half-open exam windows; execution's ownership re-test, r16, cap compatibility, `TRANSFERRED` writes; the three `void_reason`s. **r_tenders.py**: amount floor/multiplier/ceiling arithmetic and all three worked examples; 72h snapped `deadline_at`; agent-only response; frozen only on accept; inclusive deadline; decline writes nothing else; sweep lapse. **r_medical.py**: `minimum_stay_days` table; return-window derivation and closed-interval activation; half-open exam-window collision including touching endpoints; 14-day `expires_at` and its strict validity boundary; `ERR_INVALID_EXAM_STATE`; the failed-result trade cascade's three ordered steps. **r_compliance.py**: the 7 ordered violation codes; the whole posture ladder including the GRACE boundary instant and the freeze threshold; the single violation-free exit edge; the final-vs-provisional `cap_space_cents` subtlety; sweep-row immutability; all five steps' strict-vs-inclusive comparisons; event mode performing none of them.

Pass B hand-off verdicts:
1. **§2.8 r36 "affected designation"** — confirmed too loose, and the mismatch was wider than reported: impl has *three* widths, and `POST /waiver-requests/{id}/withdraw` was missing from the applies-to list entirely. Rule 36 now spells out all three and lists five operations.
2. **Option companions with `option_type: NONE`** — confirmed storable (unconditional copy). Pinned in §3.4 as stored-and-rendered-but-inert, with the reason they never lapse. §3.3 also now pins the `NONE` default.
3. **`player_active_contract` tie-break** — **reachable**, so it was pinned rather than left alone. Two `SIGNING` filings opened while a player is `UNROSTERED` (§2.6 explicitly blesses concurrent drafts) can both be approved, because neither `file_transaction` nor `_approve` re-tests the player's designation; the sole call site (r_waivers.py:46) then exposes the choice as the wire's `contract_id`. §3.6 now pins "the earliest-created one".

### Step 9 aggregate + orchestrator verification

- **Totals across the three passes: 69 edits — 47 ambiguity-pins, 22 mismatch-revisions.**
- `PRD_FINALIZED.md` 514 lines / 115,707 chars → `PRD_COMPLETED.md` **515 lines / 135,206 chars** (+1 line, **+19,499 chars**, +16.9% by character). The single added line is one new bullet in §2.2's existing error-format list; every other edit is in-paragraph. No new sections.
- Orchestrator-verified independently: `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (so the scan genuinely ran — the known silent-no-op failure mode did not occur), all five top-level sections `## 1.`–`## 5.` are present and in order, §4 still carries exactly **51** endpoint rows, §5 still carries exactly **57** error rows, and the document still terminates at `| ERR_TRADE_CAP_INCOMPATIBLE | 409 |`. Not truncated.
- Steps 8 and 9 edited documentation only. Last modification to any file under `implementation/` was `store.py` at 14:18:54; the verified 8-round green sweep launched at 14:28:56, i.e. **after** the final implementation change. The 8/8 × 159/159 result therefore attests to the implementation as it now stands, and no re-run was required after Steps 8–9.

**PIPELINE COMPLETE.** `workspace/PRD_COMPLETED.md` written; all nine steps executed.
