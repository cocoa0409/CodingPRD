# Worklog — task_2680_bank_merger_application_community_impact_review

## Step 1: Create task directory — 2026-09-04T05:44:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2680_bank_merger_application_community_impact_review` and its `workspace/` subdirectory. Index 2680 was pre-assigned by the orchestration harness (no scan/allocation performed, per instructions, to avoid collisions with the ~32 concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-04T07:11:30.000Z

All three scaffold artifacts are complete and the linter is clean.

## Files

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2680_bank_merger_application_community_impact_review/SCAFFOLD.yaml` | 3060 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2680_bank_merger_application_community_impact_review/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1690 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2680_bank_merger_application_community_impact_review/SCAFFOLD_CORNER_DESIGN.yaml` | 4256 |

## SCAFFOLD.yaml contents (§1.0–§1.7 only; no design keys present)

Top-level keys: `scenario`, `domain_name: bank-merger-application-review`, `api_prefix: ""`, `response_envelope`, `complexity_profile`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles`.

- 15 entities, 65 endpoints, 12 state machines (parallel shape: filing / review / post-closing dimensions), 2 concurrency rules (both OCC on `expected_application_version`), 11 calculations, 37 validations (single global priority ladder 1-37), 62 errors, 5 roles (Filer entity-backed to Institution, PublicCommenter, CaseAnalyst, ApprovingOfficial, ComplianceMonitor).
- `difficulty_level: expert_plus`; layers `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`, `optimistic_concurrency`; `role_model: segregation_of_duties`; `consistency_model: immediate`.

## Design index instance counts

- **SCAFFOLD_DIFFICULTY_DESIGN.yaml — 18 instances**, exactly 2 per each of the 9 Difficulty Rules (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).
- **SCAFFOLD_CORNER_DESIGN.yaml — 83 instances** across all 9 §1.9 sections: entities 12, state_machines 17, calculations 14, validations 9, endpoints 5, errors 16, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1. Of those, 62 carry full `test_recipe`s and 21 are `excluded_because` stubs (no `test_recipe`), every one citing a §1.8 instance name that exists.

## Verification

- `scaffold_lint.py` -> `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (846 calls scanned across 18 + 62 recipe-bearing instances). Two fixes were needed on the final pass: a capture path `$.data.post_mitigated_hhi` -> `$.data.hhi_post_mitigated` (the declared CompetitiveAnalysis field), plus the matching assert/setup wording (`hhi_delta_unmitigated`, `required_divestiture_deposits_usd`).
- All three files parse as valid YAML; each design file has exactly one top-level key and `SCAFFOLD.yaml` contains neither design key. Instance names are unique within and across both design files.
- Every one of the 62 declared error ids is referenced by at least one design instance (checked programmatically; the errors section closes the gaps left by §1.8 — the 11-way not-found sweep, ERR_UNAUTHENTICATED, ownership/uniqueness/sequence/timing families).
- Built entirely with chunked `cat >>` appends; no sibling `task_*/` directory was listed, read, or grepped at any point.

Orchestrator verification: all three files present, task dir intact (workspace/ + worklog.md not wiped).

## Step 3: Copy Shared Files — 2026-09-04T07:12:10.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` -> `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T07:23:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **499 lines** (~63 KB), built by 5 chunked appends. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read.

**Section list**

- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Resource Properties and the Logical Clock · 2.5 Rejection Precedence · 2.6 Optimistic Concurrency on the Application Record · 2.7 Measurement Precision and Rounding · 2.8 The Includable Branch Set · 2.9 Cascade Discipline and Compensating Actions · 2.10 Two Interval Conventions
- §3 Business Logic & Workflows — 3.1 Institutional/Banking-Market Record · 3.2 Structuring the Transaction and Scoring Management · 3.3 Pro Forma Capital on Two Bases · 3.4 Filing, Acceptance and the Amendment Cycle · 3.5 Deposit-Market Concentration and the Divestiture Requirement · 3.6 Branch Designations · 3.7 The Public Comment Record · 3.8 Hearing Petitions and the Divergent Grant/Denial Cascades · 3.9 Community Benefits · 3.10 Recommendation, Decision Order and Statutory Waiting Period · 3.11 Consummation, Systems Conversion and Customer Disclosure · 3.12 Post-Closing Commitment Monitoring · 3.13 The Consolidated Clearance Read
- §4 Endpoint Definitions (4 columns, 65 rows)
- §5 Error Code Catalogue (2 columns, 62 rows) — file ends here, at a complete table row

**Hard Contracts**

Field coverage check: entities[].fields 136/136 unique required present, 0 missing (161 field entries / 15 entities); endpoints[].request_body 74/74; query_params 23/23; path_params 1/1; clearance-summary computed keys (15) + `now` all present. Status: PASS

Rule coverage check: 37/37 validations expressed as an explicit ordered list in §2.5; 2/2 OCC rejections; 50/50 state-machine transitions fully expressed; 11/11 calculations incl. all 4 variant branches; 34/34 endpoint side_effects/applies_to; 161/161 structured field contents reconstructible; 7 sibling-branch symmetry groups equal-density, 0 asymmetric; all 100+ enum/state strings verbatim. Status: PASS

Path purity check (§3 only): 1010 backtick tokens scanned, 0 leading-`/` tokens, 0 bare HTTP-method tokens, 0 method+path tokens, 0 stray unbackticked URL paths. Status: PASS

Also verified: §2.2 byte-identical to `section-2.2-response-structure.md`; all 65 endpoint role sets match `endpoints[].roles` exactly; all 62 error IDs appear in §2/§3 prose; zero fuzzy words. `DIVESTITURE_STEP_USD: 1000000` rendered in business prose per the constants guideline.

Orchestrator truncation guard: `tail -25` shows the file ending on a complete §5 table row; independent cross-check confirms 62/62 scaffold error ids present in the §5 table (none missing, none extra) and 65/65 scaffold endpoint paths present in §4. No truncation — no regeneration needed.

## Test generation complete (test_helpers/ + test_suite/)

- Stage 1: `test_helpers/` — 9 modules (types, api_client, api_errors, constants, factories,
  test_users, assertions, fixtures, __init__), 2,306 lines.
- Stage 2: `test_suite/` — conftest.py plus 17 test modules, 4,735 lines, 136 tests.
  - Queue A (difficulty index): test_01–test_07, 55 tests, 18 of 18 instances translated.
  - Queue B (corner index): test_08–test_17, 81 tests, 62 of 62 non-stub instances translated;
    the 21 `excluded_because:` stubs were not translated (by contract).
- Every test docstring carries exactly one `Design:` tag resolving verbatim to a source
  instance name; every `PRD §x.y: "…"` citation was verified greppable in workspace/PRD.md
  with the section label re-checked against the heading map.
- `python3 -m compileall` clean on both directories; no unused imports; no stray test dirs
  under workspace/.

## Step 5: Generate Unit Tests — 2026-09-04T08:26:00.000Z

Test generation is complete. All work lives at the task root of `/home/ubuntu/github/CodingPRD/tasks/task_2680_bank_merger_application_community_impact_review/`.

## Files written

`test_helpers/` (2,306 lines): `types.py` 532, `fixtures.py` 759, `assertions.py` 248, `api_client.py` 235, `factories.py` 188, `api_errors.py` 136, `constants.py` 108, `test_users.py` 56, `__init__.py` 44.

`test_suite/` (4,735 lines, 136 tests): `conftest.py` 46; queue A — `test_01_pro_forma_capital.py` 151/5, `test_02_management_scoring_and_filing_gate.py` 161/7, `test_03_competitive_screen.py` 159/8, `test_04_branch_designations.py` 257/9, `test_05_comment_windows_and_hearings.py` 227/9, `test_06_decisions_and_systems_conversion.py` 150/5, `test_07_commitment_monitoring.py` 381/12; queue B — `test_08_entity_records_and_reads.py` 336/12, `test_09_lifecycle_transitions.py` 453/12, `test_10_derived_arithmetic.py` 400/9, `test_11_validation_gates.py` 226/6, `test_12_endpoint_surfaces.py` 289/6, `test_13_identity_and_ownership_errors.py` 220/6, `test_14_integrity_and_uniqueness_errors.py` 333/6, `test_15_decision_and_monitoring_errors.py` 454/13, `test_16_role_partitioning.py` 290/6, `test_17_concurrency_and_visibility.py` 202/5.

## Coverage

- Queue A (difficulty index): 18 of 18 instances translated, 0 skipped — 55 tests.
- Queue B (corner index): 62 of 62 non-stub instances translated, 0 skipped — 81 tests, covering entities 12, state_machines 11, calculations 7, validations 5, endpoints 4, errors 16, rbac 4, cross_cutting_complexity_layers 2, consistency_model 1. The 21 `excluded_because:` stubs were not translated, per contract.
- No instance failed the PRD-first filter, so there are no gap/skip entries to report.

## Verification run

- `python3 -m compileall` clean on both directories; AST check shows no unused imports in any file.
- Tag sweep: 136 tests, each with exactly one `Design:` line as the final docstring line, all 80 names resolving verbatim to a `name:` in the source yaml; no dual tags, no stub tags.
- Citation sweep: every `PRD §x.y: "…"` quote was matched verbatim (whitespace-normalized) against `workspace/PRD.md`, and each cited section label was re-validated against the `### ` heading map — 0 mismatches (this caught nothing new after the earlier §3.13/§3.10 fix).
- `ls -la` on the task root and on `workspace/` confirms `test_helpers/` and `test_suite/` exist only at the root; nothing under `workspace/` except `INSTRUCTION.md`, `PRD.md` and the untouched `implementation/`. `__pycache__` from my compile checks was removed.

## Key findings worth relaying

Three corner recipes assert outcomes the PRD contradicts; I translated the PRD-derivable claim and dropped the contradicted one rather than weakening or skipping:

1. `consummation_is_rejected_before_the_window_opens_and_after_it_lapses` claims the order is "still ISSUED after both attempts", but §3.11 moves `ISSUED -> LAPSED` before returning `ERR_CONSUMMATION_WINDOW_LAPSED`. Test asserts LAPSED, plus the PRD's follow-on that a second attempt then reports `ERR_INVALID_DECISION_STATE` (409).
2. `consummation_with_an_open_pre_consummation_condition_is_rejected` includes a positive control that satisfies a DIVESTITURE condition, which §3.10 gates on posture `CLEARED`/`CLEARED_WITH_DIVESTITURE` — unreachable in that market-free world. Replaced with the derivable control that an OPEN `POST_CLOSING` condition does not block consummation.
3. Two error/monitoring recipes execute a benefits plan against a DRAFT application, which §3.9 forbids; routed through `application_under_review()` / `monitoring_world()` instead. Same for `the_recommending_analyst_cannot_also_issue_the_decision`, whose recipe expects `filing_status` UNDER_REVIEW after a recommendation — the test asserts RECOMMENDED per §3.10.

One recipe assertion I omitted as non-derivable: the "clock is still 2026-08-01" claim in the RBAC refusal test (nothing in the PRD binds `created_at` to the logical clock); the clock's integrity is instead proven in the positive-control test via the comment period's `opens_at`.

Orchestrator verification: `test_helpers/` and `test_suite/` are at the task root; no stray copies under `workspace/`.

## Step 6: Generate Implementation — 2026-09-04T07:54:00.000Z

Implementation complete and smoke-verified.

## Files written
All under `workspace/implementation/`: `start.sh` 10 (executable), `requirements.txt` 1, `app.py` 86, `db.py` 162, `errors.py` 89, `response.py` 49, `middleware.py` 189, `calc.py` 293, `aggregates.py` 310, `helpers.py` 181, `routes/__init__.py` 0, `routes/clock.py` 17, `routes/institutions.py` 86, `routes/markets.py` 50, `routes/branches.py` 242, `routes/applications.py` 387, `routes/schedules.py` 105, `routes/analyses.py` 58, `routes/periods.py` 114, `routes/comments.py` 154, `routes/hearings.py` 184, `routes/plans.py` 208, `routes/decisions.py` 349, `routes/conversions.py` 186, `routes/reports.py` 305. Total 3815 lines. `__pycache__` dirs removed.

## Endpoint count
**65 registered Flask rules**, exactly matching the 65 `- method:` entries in `SCAFFOLD.yaml` (and the PRD §1.3 table). Includes `POST /_clock/set_current_utc`.

## Storage / boot discipline
- In-memory only: 15 plain dicts in `db.Store`, reset on construction. `grep` for `sqlite3`, `open(`, `json.dump`, `/tmp`, `pickle` across all modules returns nothing.
- No seeding: a freshly booted server reports `total_count == 0` for all 15 collections, and the logical clock reads the epoch `2026-08-01T00:00:00.000Z` until `/_clock/set_current_utc` is called.
- `app.run(host="0.0.0.0", port=$PORT or 10000, threaded=False, use_reloader=False)` — clean per-invocation boot for `--isolation per-test-server`.

## Smoke test (passed)
Booted via `bash start.sh` on explicit ports 18742 then 18919; killed **only** pids 2958865 and 3021564 (no broad `pkill`). Envelope matches PRD §2.2: `{meta:{api_request_id:"req_"+20, api_request_timestamp:"…Z" 3-dp}, response_type:"object"|"array"|"error", data:{…}}`; list responses add `limit/offset/total_count/has_more` inside `meta` with `response_type:"array"`.

End-to-end lifecycle exercised on one run: create 3 institutions + market + 3 branches (market aggregates `total_deposits 1,000,000,000`, `participant_count 3`, `hhi_current 3800`) -> application (`management_composite_score 80.53`, `SATISFACTORY`, `DRAFT`/`NOT_OPEN`) -> pro-forma schedule both bases (REGULATORY_ADJUSTED 10.34/8.71 `WELL_CAPITALIZED`; INTERNAL_STRESS 9.57/8.16) with OCC 412 `ERR_STALE_APPLICATION_VERSION` on a stale `expected_application_version` -> competitive analysis (pre 3800, post 5000, delta 1200, `PRESUMPTIVE_VIOLATION`, required divestiture 139,000,000) -> posture `BLOCKED` -> divestiture designation cascade (analysis recomputed to designated 200,000,000, `hhi_post_mitigated 3800`, `mitigation_satisfied true`, version 2; posture -> `CLEARED_WITH_DIVESTITURE`) -> submit/accept (`UNDER_REVIEW`/`OPEN_FOR_COMMENT`, `earliest_decision_at 2026-09-15`) -> auto-created comment period -> comment -> close -> recommend -> clearance summary -> decision `CONDITIONALLY_APPROVED` (`waiting_period_days 15`, window `2026-10-05` -> deadline `2027-03-19`) -> PRE_CONSUMMATION condition -> benefits plan (1000 committed, annual 500, quarterly 125) + line item -> execute -> satisfy condition -> consummate (target `MERGED_OUT`, only its OPEN branches reassigned so the acquirer holds 1 branch/300,000,000; app `CONSUMMATED`/`MONITORING`) -> performance report (`credited 200`, `fulfillment_pct 160.0`) -> review `ACCEPTED` (ledger 200/800, `COMPLIANT`, 1 filed) -> reopen restores exactly 0/1000/0 filed, preserving the `credited_to_date + remaining == total_committed` partition.

A separate branch exercised the protest path: substantive PROTEST -> `PROTEST_PENDING`, hearing request -> `HEARING_PENDING`, grant -> period `EXTENDED` (+30 days, `closes_at 2026-09-30`), `HEARING_GRANTED`, `earliest_decision_at` recomputed to `2026-10-15`; respond -> `RESPONDED`; close -> `COMMENT_CLOSED`; and `recommend` correctly rejected with 422 while posture was `BLOCKED`.

Error surface spot-checks: 401 `ERR_UNAUTHENTICATED` (unknown role), 403 `ERR_ROLE_NOT_PERMITTED`, 404 `ERR_INSTITUTION_NOT_FOUND`, 400 `ERR_INVALID_REQUEST` (`limit=101`, missing required field), 409 `ERR_DUPLICATE_MARKET_CODE`, 422 `ERR_REGULATOR_CHARTER_MISMATCH`, and pagination `?limit=2&offset=1` -> `total_count 3`, `has_more false`, 2 items.

Note: the three `KeyError`s hit during smoke testing were the probe script guessing field names/enums that the spec does not define (`hhi_delta_mitigated`, `plan.executed_at`, `timing: PRE_CLOSING`); the implementation matches the scaffold in each case (no such fields; timing enum is `{POST_CLOSING, PRE_CONSUMMATION}`). No implementation changes were needed this session. `test_suite/` and `test_helpers/` were never read or listed, and no sibling task dir was accessed.

## Step 7: Iterate Tests + Fixes — 2026-09-04 (diagnostic loop)

Ran the 8-round parallel stability sweep (`--isolation per-test-server`, 136 tests) three times. Final sweep: all 8 rounds **136/136 passed**, ~266 s per round. `results.{1..8}.json` left in `workspace/implementation/`.

### Iteration 1 — collection failure (1 test collected, 0 passed)
`test_suite/test_16_role_partitioning.py` imported `build_user_headers` from `test_helpers`, which does not re-export it, so the whole module failed to import and pytest aborted collection for the entire suite. Moved the import to `prd_bench_local_runner.testing`, matching `test_13_identity_and_ownership_errors.py`.

### Iteration 2 — 133/136 passed, the same 3 failures in all 8 rounds (no flakiness)
All three were STEP 2 test bugs (setup/assertion inconsistent with PRD); no implementation change was needed.

1. `test_14::TestIntakeGuards::test_01_a_self_merger_and_a_schedule_without_denominators_are_refused` — the module-level `THIN_CAPITAL_INSTITUTION` fixture declared `charter_type: SAVINGS` with `primary_regulator: OCC`. PRD §3.1: "both a `STATE_NONMEMBER` charter and a `SAVINGS` charter require `FDIC`. A mismatched pair is refused with `ERR_REGULATOR_CHARTER_MISMATCH`." The PRD-faithful implementation correctly returned 422 during setup. Changed the regulator to `FDIC`.
2. `test_16::TestEntityBackedFilerIdentity::test_06_a_stranger_files_its_own_case_but_cannot_amend_another` — the setup filed an application with `consideration_type="CASH"`, not a declared enum member. PRD §3.2: "The `consideration_type` is one of `ALL_CASH`, `ALL_STOCK` or `MIXED`". Changed to `ALL_CASH` at all four occurrences across `test_14` and `test_16` (the two in `test_14::test_01` and `test_16::test_01` were masked by earlier precedence levels but were equally unfaithful).
3. `test_14::TestClosureNoticeCompleteness::test_05_a_closure_designation_needs_both_dates_and_ninety_days_of_lead` — asserted the market's `total_deposits_usd` was `250_000_000` after a closure designation, but `rosewood_market_world()` builds a 1,000,000,000 base (200M + 50M + 400M + 250M + 100M); 250M is one competitor's branch. The assertion's *intent* is PRD §2.8 ("designating a branch for divestiture or for closure does **not** remove its deposits from the market's deposit base"), which the implementation honours — the expected constant was simply mis-transcribed. Corrected to `1_000_000_000`, which is the value §2.8 requires.

### Iteration 3 — clean
8/8 rounds green, 0 failures, 0 errors, 0 flaky tests.

No tests deleted (no PRD-silence or unique-derivability failures found). No changes to `test_helpers/`. No changes to `workspace/implementation/`.

## Step 7: Run Tests and Iterate — 2026-09-04T09:14:00.000Z

Clean exit — all 8 parallel rounds passed 136/136.

## Summary

**Iterations run:** 3 (each an 8-round parallel `per-test-server` sweep of 136 tests). Final sweep: 8/8 rounds at 136 passed / 0 failed / 0 errors, ~266 s per round. `results.{1..8}.json` left in `workspace/implementation/`.

**Tests deleted:** none. No failing test hit STEP 1a PRD-silence or STEP 1b unique-derivability collapse — all three real failures were STEP 2 test-vs-PRD consistency bugs.

**Fixes applied to `test_helpers/`:** none. The fixtures/factories were faithful; the bugs lived in `test_suite/` overrides.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on every failure; in each case the PRD-faithful server correctly rejected a request the test had malformed.

**Fixes applied to `test_suite/`:**

- `test_16_role_partitioning.py` — import of `build_user_headers` moved from `test_helpers` (which never re-exported it) to `prd_bench_local_runner.testing`, matching `test_13`. This was the blocker in iteration 1: the module failed to import, pytest aborted collection for the *whole* suite, and every round reported `total: 1, passed: 0` — a collection failure masquerading as a total wipeout.
- `test_14_integrity_and_uniqueness_errors.py`, `THIN_CAPITAL_INSTITUTION` — `primary_regulator` `OCC` -> `FDIC`. PRD §3.1: "both a `STATE_NONMEMBER` charter and a `SAVINGS` charter require `FDIC`." The server was right to return `ERR_REGULATOR_CHARTER_MISMATCH` during setup.
- `test_14` + `test_16`, 4 occurrences — `consideration_type="CASH"` -> `"ALL_CASH"`. PRD §3.2 declares only `ALL_CASH`, `ALL_STOCK`, `MIXED`. Two of the four were masked by earlier rejection-precedence levels but were equally unfaithful, so all four were corrected.
- `test_14::test_05` — expected market `total_deposits_usd` `250_000_000` -> `1_000_000_000`. `rosewood_market_world()` builds a 1,000,000,000 base (200M + 50M + 400M + 250M + 100M); 250M is one competitor's single branch. The assertion's own docstring cites PRD §2.8 ("designating a branch ... does **not** remove its deposits from the market's deposit base"), which the implementation honours — only the expected constant was mis-transcribed, so the fix makes the test *more* faithful to the rule it claims to test.

**Flakiness:** none observed. The 3 iteration-2 failures reproduced identically in all 8 rounds, and iteration 3 was green in all 8 — no timing-sensitive or load-induced failures, and no sweep reaping (every round ran the full 136 to completion under `setsid`).

Orchestrator verification: independently re-read all 8 `results.*.json` — each reports `passed 136 / total 136`. Step 8 is NOT skipped: the skip condition requires zero fixes in all four categories, and Step 7 applied 4 `test_suite/` fixes (even though deletions, `test_helpers/` fixes and `implementation/` fixes were all zero).

## Step 8: Finalize PRD — 2026-09-04T09:04:00.000Z

## Result

`workspace/PRD_FINALIZED.md` created. **Zero edits were warranted.** All four `<step_7_diff>` items are test-side bugs against PRD passages that are already fully explicit and already exactly matched by the implementation. Patching any of them would have restated prose already present verbatim, and inventing edits elsewhere would violate the hard scope.

### Line counts
- `PRD.md`: 499 lines
- `PRD_FINALIZED.md`: 499 lines
- Delta: **0 lines, 0.00%** (byte-identical, md5 `6c6f3cccdf2935ac86412e7126d98324` — intentional, not a copy failure)

### Change list
- *(none)*

### Per-item verification log (mandatory subject + enumerated impl paths, run for every item as if it were an edit)

**1. `test_16` import of `build_user_headers` moved to `prd_bench_local_runner.testing`**
- (a) Subject: test-module import plumbing / helper re-exports.
- (b) Enumerated: nothing in `implementation/` is reachable from this subject — `test_helpers/__init__.py` never re-exported the symbol, and `implementation/middleware.py` (header parsing, `require_roles`, `ALL_ROLES`, `READ_ROLES_NO_COMMENTER`) is the only server-side counterpart, which is unaffected by which module the test imports a header builder from. Grepped `implementation/` for `build_user_headers` — no hits.
- (c) No wording change. Pure test-infrastructure bug; PRD §2.1 role/header contract is untouched. **No edit.**

**2. `THIN_CAPITAL_INSTITUTION` `primary_regulator` `OCC` -> `FDIC`**
- (a) Subject: the charter-class -> primary-regulator mapping and its rejection.
- (b) Enumerated every impl path touching `charter_type`/`primary_regulator`: `routes/institutions.py:21-29` (`CHARTER_TYPES`, `REGULATORS`, `REQUIRED_REGULATOR`), `:45-46` (both required via `req_enum`, so an undeclared member is `ERR_INVALID_REQUEST` at §2.5 step 4), `:51-55` (the mismatch raise), `:86` (list filters), `errors.py:64` (422). There is no second write path — no PATCH/update endpoint for institutions anywhere in `routes/`, so the mapping is enforced at exactly one site.
- (c) No wording change needed. `REQUIRED_REGULATOR` is character-for-character PRD §3.1 line 194 ("`NATIONAL` -> `OCC`, `STATE_MEMBER` -> `FRB`, both `STATE_NONMEMBER` and `SAVINGS` -> `FDIC`"), and the error/status pair matches §2.5 step 29 plus the §5 catalogue. The server was right to reject `SAVINGS`+`OCC`. **No edit.**

**3. `consideration_type="CASH"` -> `"ALL_CASH"` (4 occurrences across `test_14`, `test_16`)**
- (a) Subject: the `consideration_type` enumeration and where it is validated.
- (b) Enumerated all six impl references: `routes/applications.py:39` (`CONSIDERATION_TYPES`), `:68` (required on create), `:83` (persisted), `:127` (optional on amend, same tuple), `:148-149` (applied on amend). Also confirmed the field is purely descriptive downstream — grepped the whole tree: no other module reads `consideration_type` (unlike `structure`, which `calc.waiting_period_days` consumes), so no derived value depends on it. Both the create and amend paths use the identical three-member tuple, so a widened or narrowed PRD sentence would have had to hold for both.
- (c) No wording change. PRD §3.2 line 204 already declares exactly `ALL_CASH`, `ALL_STOCK`, `MIXED`, and `"CASH"` is correctly `ERR_INVALID_REQUEST` under §2.5 step 4 — which is also why two of the four occurrences were masked by earlier precedence levels. **No edit.**

**4. `test_14::test_05` expected market `total_deposits_usd` `250_000_000` -> `1_000_000_000`**
- (a) Subject: whether a designated branch's deposits remain in the market/institution deposit base (the includable set).
- (b) Enumerated every impl path that can move a market or institution deposit aggregate: `calc.py:63` (`INCLUDABLE_BRANCH_STATUSES = OPEN, DESIGNATED_FOR_DIVESTITURE, DESIGNATED_FOR_CLOSURE`), `aggregates.py:7-29` (`includable`, `market_branches`, `institution_branches`, `deposits_by_institution`), `aggregates.py:35-67` (`recompute_market`, `recompute_institution`, `recompute_market_ids`), and every callsite of those recomputes: `routes/branches.py:67-68` (branch creation), `routes/decisions.py:139` (denial unwind), `routes/decisions.py:338` (consummation reassignment + divestiture), `routes/conversions.py:184` (conversion closing branches). Critically, confirmed the *designate* and *rescind* handlers (`routes/branches.py:156-207`, `:210-242`) call only `recompute_analyses_for_market` / `rollup_posture` / the condition cascades — never `recompute_market` or `recompute_institution` — so designation and rescission provably leave the deposit base and `branch_count` untouched, while only actual `DIVESTED`/`CLOSED` transitions drop a branch out of the includable set.
- (c) No wording change. This is exactly PRD §2.8 lines 166-170, which the test's own docstring cites; only the expected constant was mis-transcribed (250M is one competitor's single branch, not the 1,000,000,000 base built by `rosewood_market_world()`). **No edit.**

### Note for Step 9
The byte-identity here is a deliberate finding, not a skipped scan: Step 7 reported zero `implementation/` fixes, zero `test_helpers/` fixes and zero test deletions, and classified all three real failures as STEP 2 test-vs-PRD consistency bugs. Every one of those three traces to a PRD sentence that is explicit and correctly implemented, so no PRD silence or PRD/impl mismatch is exposed by this diff.

Orchestrator decision: Step 8's byte-identical output is accepted as a legitimate finding (zero implementation fixes upstream), but because a byte-identical Step 9 output would instead indicate the scan never ran, Step 9 will be executed as THREE sequential file-partitioned passes over the 3815-line implementation rather than one pass, each pass editing `PRD_COMPLETED.md` in place.

## Step 9: Complete PRD — 2026-09-04T10:00:00.000Z

Executed as THREE sequential file-partitioned passes over the 3815-line implementation (orchestrator decision recorded in the Step 8 entry: a single pass risks a silent no-op, and a byte-identical PRD_COMPLETED.md would be indistinguishable from a scan that never ran).

### Sizes

| file | lines | chars |
|---|---|---|
| `PRD.md` | 499 | 100,006 |
| `PRD_FINALIZED.md` (Step 8, byte-identical to PRD.md) | 499 | 100,006 |
| `PRD_COMPLETED.md` after pass 1 (core modules) | 499 | 104,286 |
| `PRD_COMPLETED.md` after pass 2 (routes A) | 501 | 111,973 |
| `PRD_COMPLETED.md` after pass 3 (routes B) | 501 | 122,061 |

Overall vs source: **+2 lines / +22,055 chars**. md5 differs from PRD.md/PRD_FINALIZED.md (`a765cf6f257acb240984fa282940fb96` vs `6c6f3cccdf2935ac86412e7126d98324`) — the scan demonstrably ran. Heading count unchanged at 31 (no new sections); file still ends on a complete §5 error-catalogue table row.

### Totals

**59 discrete changes: 46 ambiguity-pins, 13 mismatch-revisions.** Pass 1: 12 pins / 0 mismatches (partition: app.py, db.py, errors.py, response.py, middleware.py, calc.py, aggregates.py, helpers.py). Pass 2: 16 pins / 3 mismatches (routes/clock, institutions, markets, branches, applications, schedules, analyses). Pass 3: 18 pins / 10 mismatches (routes/periods, comments, hearings, plans, decisions, conversions, reports).

### Pass 1 changes (core modules)

- §2.1 — revise — ambiguity — a present-but-blank `X-User-ID`/`X-User-Role` counts as absent (401); role names match exactly — `middleware.py:26-30`.
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`-`Z`/`0`-`9` — `response.py:8,12`.
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the host wall clock, the one timestamp that does not read the §2.4 logical clock — `response.py:15-17`.
- §2.3 — revise — ambiguity — non-base-ten pagination value is malformed; an empty-string param takes its default — `middleware.py:165-185`.
- §2.3 — revise — ambiguity — `created_at` ties break by creation order (oldest-inserted first) — `db.py:159-162`.
- §2.3 — revise — ambiguity — empty-string filters ignored, as is any param that is not `limit`/`offset`/a declared filter — `helpers.py:47-58`.
- §2.5 step 4 — revise — ambiguity — six body-shape conventions (explicit `null` == omitted; bools rejected for ints and numbers/bools for strings; min length on stripped value, max on value as supplied, stored untrimmed; timestamps accept `Z`/offset/no-zone/date-only; omitted body read as `{}` where nothing is required, non-object body fails; a body FK that is not a non-blank string fails at step 4 not step 8) — `middleware.py:56-96,114-121,150-156`, `db.py:73-88`, `helpers.py:37-41`.
- §2.7 — revise — ambiguity — the five 2dp fields are JSON numbers (`70.0`, `0.0`); zero denominator yields `0.00` not null/error; negatives carry through — `calc.py:66-90`.
- §2.9 — revise — ambiguity — three refinements applying to every record: at most one version bump per request; a recompute producing identical values is not a mutation; a record created by the request is never re-bumped by its own cascade (reads back at version 1) — `db.py:104-152`.
- §3.3 — revise — ambiguity — `capital_adequacy_flag` bands the ratios AFTER 2dp rounding (6.996% -> 7.00 meets the floor) — `calc.py:230-242`.
- §3.13 — revise — ambiguity — `worst_screen_result` severity order `PRESUMPTIVE_VIOLATION` > `MITIGATION_REQUIRED` > `PASS` — `calc.py:147`.
- §4 — revise — ambiguity — trailing slash optional on every path; `ERR_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405 / `ERR_INTERNAL` 500 exist outside the §5 catalogue — `app.py:30,54-71`, `errors.py:78-80`.

### Pass 2 changes (routes A)

- §2.4 — insert — ambiguity — clock response is `{"now": …}` at 200 echoing the caller's exact string while storing the normalized instant — `routes/clock.py:17`.
- §2.5 step 4 — insert — ambiguity — a USD amount required `> 0` fails step 4 (400) when supplied as 0 — `helpers.py:96`.
- §2.5 step 5 — revise — **mismatch** — PRD ordered ownership (5) ahead of body-FK existence (8); impl resolves the application-bearing body reference first — `routes/branches.py:140-141`, `routes/schedules.py:49-50`.
- §2.6 — insert — ambiguity — `expected_application_version` is an integer >= 0; negative fails 400, 0 passes shape then fails 412 — `routes/schedules.py:45`.
- §3.1 — insert — ambiguity — `cra_exam_closed_at` is a non-blank free-form string stored verbatim, never parsed — `routes/institutions.py:49`.
- §3.1 — insert — ambiguity — `market_code` uniqueness exact/case-sensitive; `market_name` >= 1 non-blank char, no maximum — `routes/markets.py:20,24`.
- §3.1 — insert — ambiguity — branch `institution_id` resolved before `market_id` — `routes/branches.py:48-49`.
- §3.2 — insert — ambiguity — no ownership check at application creation; any Filer may name any acquirer — `routes/applications.py:62-77`.
- §3.2 — insert — ambiguity — `acquirer_id` before `target_id`, both before the self-merger test — `routes/applications.py:74-77`.
- §3.2 — revise — **mismatch** — amendable states enumerated (incl. `RECOMMENDED`) with `ERR_INVALID_APPLICATION_STATE`; `version` bumps unconditionally even on a no-op body — the one exception to §2.9 — `routes/applications.py:125,140,155`.
- §3.3 — revise — ambiguity — all six purchase-accounting adjustments required, no defaults — `routes/schedules.py:47`.
- §3.4 — insert — ambiguity — accept refusal is `ERR_COMMENT_PERIOD_OVERLAP`; the window test ignores period `status`; axis moves only from `NOT_OPEN` — `routes/applications.py:222-252`.
- §3.4 — insert — ambiguity — the return edge leaves `earliest_decision_at` and each period's `closes_at` untouched; `reason` validated but never persisted — `routes/applications.py:274-279`.
- §3.5 — insert — ambiguity — `application_id` before `market_id`; no `filing_status` gate on running a screen — `routes/analyses.py:21-22`.
- §3.5 — insert — ambiguity — the consummation freeze bars recomputation only; a first-time analysis may still be created and re-rolls posture — `aggregates.py:144-146`.
- §3.6 — insert — ambiguity — designate: party mismatch -> `ERR_INVALID_BRANCH_STATE`, terminal application -> `ERR_INVALID_APPLICATION_STATE`; order branch-status -> party -> filing-status — `routes/branches.py:143-154`.
- §3.6 — insert — ambiguity — the divestiture condition cascade reaches the decision at any `status`; notice dates supplied with a divestiture are shape-checked then discarded — `routes/branches.py:91,156-165`.
- §3.6 — insert — ambiguity — the closure blackout test reads the conversion plan at any `status`; `notice_sent_at`/`planned_closure_date` stored and returned as the caller's exact strings — `routes/branches.py:184-204`.
- §3.6 — revise — **mismatch** — rescind reads no body at all; branch-state precedes filer ownership, inverting §2.5 — `routes/branches.py:212-221`.
- §3.10 — insert — ambiguity — both the review-status and elapsed-review gates on recommend surface `ERR_INVALID_APPLICATION_STATE` (never `ERR_WAITING_PERIOD_NOT_ELAPSED`); a null `earliest_decision_at` refuses — `routes/applications.py:295-307`.
- §3.13 — insert — ambiguity — full null/empty clearance-summary shapes, notably `all_markets_mitigated` vacuously true with zero analyses, `worst_screen_result` null, schedule fields null — `routes/applications.py:341-386`.

### Pass 3 changes (routes B)

- §2.5 step 4 — revise — **mismatch** — added `affected_customer_count` to the "strictly greater than 0" integer enumeration — `routes/conversions.py:47`.
- §3.7 — revise — **mismatch** — `duration_days` stored range corrected 1-90 -> **7-90 inclusive** — `routes/periods.py:40-42`.
- §3.7 — insert — ambiguity — `opens_at` echoed as the exact string supplied, not restamped — `routes/periods.py:51`.
- §3.7 — insert — ambiguity — the overlap scan considers every period regardless of `status`, so a `CLOSED` period still blocks — `routes/periods.py:62-69`.
- §3.7 — revise — **mismatch** — comment timeliness decided purely by clock vs `closes_at`; period `status` never read — `routes/comments.py:54-62`.
- §3.7 — revise — **mismatch** — the protest axis move requires all four of `RECEIVED`, `PROTEST`, substantive, and resulting count >= 1 — `routes/comments.py:86-91`.
- §3.7 — insert — ambiguity — acknowledge ignores any `response_body`; the RESPONDED axis return needs zero unresolved protests, no pending hearing request, and an `OPEN`/`EXTENDED` period — `routes/comments.py:147-153`.
- §3.7 — insert — ambiguity — a wrong comment state on acknowledge/respond reports `ERR_INVALID_APPLICATION_STATE` — `routes/comments.py:124,129`.
- §3.7/§3.8 — insert — ambiguity — explicit close requires `OPEN_FOR_COMMENT`/`EXTENDED`; `earliest_decision_at` re-stamped unconditionally while the axis moves to `COMMENT_CLOSED` only from `OPEN_FOR_COMMENT`, `PROTEST_PENDING` or `HEARING_GRANTED` — `routes/periods.py:93-113`.
- §3.8 — insert — ambiguity — period-open test precedes the substantive-protest test; the protest must be in a counted status; the comment is never cross-checked against the application — `routes/hearings.py:48-61`.
- §3.8 — insert — ambiguity — a grant against an already-`EXTENDED` period accumulates further days from the current `closes_at` — `routes/hearings.py:142-147`.
- §3.8 — insert — ambiguity — deny and withdraw share one axis fallback; withdraw checks the requester before the state and reads no application state — `routes/hearings.py:94-101`.
- §3.9 — insert — ambiguity — an `EXECUTED` plan blocks a new plan with `ERR_INVALID_PLAN_STATE`, checked after the version precondition — `routes/plans.py:75-85`.
- §3.9 — insert — ambiguity — a duplicate category reports `ERR_INVALID_REQUEST`, only after the plan-state test — `routes/plans.py:136-144`.
- §3.9 — insert — ambiguity — execute order is plan status -> `filing_status` -> `ERR_EMPTY_BENEFITS_PLAN` — `routes/plans.py:182-194`.
- §3.10 — insert — ambiguity — issuance order is segregation of duties -> already-issued -> `RECOMMENDED` -> posture; `expedited_processing` computed and stored for a `DENIED` order too — `routes/decisions.py:51-95`.
- §3.10 — insert — ambiguity — the DENIED branch revert clears `designation_application_id`, `notice_sent_at`, `planned_closure_date` but leaves `notice_lead_days` — `routes/decisions.py:128-137`.
- §3.10 — revise — **mismatch** — condition attachment is not gated on order status (may attach to `CLOSED`, `LAPSED`, `CONSUMMATED`) — `routes/decisions.py:170`.
- §3.10 — insert — ambiguity — the condition's own state is read before the order's; manual satisfaction is recorded as NOT cascade-satisfied, so a later rescind cannot unwind it — `routes/decisions.py:209-213,249`.
- §3.11 — insert — ambiguity — consummation precedence: decision state -> all periods `CLOSED` -> `PRE_CONSUMMATION` conditions -> window open -> deadline (with the `LAPSED` write) -> benefits plan — `routes/decisions.py:275-315`.
- §3.11 — revise — **mismatch** — only `OPEN` target branches are reassigned; a branch under a closure designation stays with the target and keeps counting toward its recomputed totals (replacing "drops the target's totals to 0") — `routes/decisions.py:326-341`.
- §3.11 — insert — ambiguity — inverted conversion dates are `ERR_INVALID_REQUEST` before FK resolution; blackout test precedes the one-plan-per-application test; both dates stored as supplied; no `filing_status` gate — `routes/conversions.py:48-84`.
- §3.11 — insert — ambiguity — the channel array is validated before the state and lead-time tests and stored verbatim including repeats; lead-time runs ahead of the mandatory-`MAIL` test — `routes/conversions.py:107-135`.
- §3.11 — insert — ambiguity — conversion recomputes each owning institution's own figures alongside the affected markets — `routes/conversions.py:184-185`.
- §3.12 — revise — **mismatch** — the gate is the named plan's own `status` being `EXECUTED` (not "no `EXECUTED` plan on the application"), ahead of duplicate-label and sequence tests; undeclared `achieved_by_category` keys are `ERR_INVALID_REQUEST`; no `filing_status` is ever read — `routes/reports.py:43-46,93-107`.
- §3.12 — revise — **mismatch** — the basis the report copied from the plan at filing decides (was "the plan's stored basis"), resolving an internal contradiction with ¶2 — `routes/reports.py:110,124-127`.
- §3.12 — revise — **mismatch** — a breaching run breaches EVERY matching `OPEN` `POST_CLOSING` `COMMUNITY_BENEFITS` condition; escalation follows only where at least one actually moved — `routes/reports.py:219-237`.
- §3.12 — revise — **mismatch** — reopen restores `consecutive_deficient_periods` exactly to its pre-review value rather than arithmetically, floors `filed_report_count` at 0, reopens only the conditions that review recorded, and an accepted reopen runs the same posture step — `routes/reports.py:263-304`.

### `duration_days` conflict — resolved

`routes/periods.py:40-42` uses `minimum=7, maximum=90`, so §2.5 step 4's "7 through 90 inclusive" was correct and §3.7's "1 through 90" was the mismatch. §3.7 now reads 7-90 inclusive, cross-referencing §2.5 step 4.

### Cross-pass consistency

Pass 3 performed the final consistency read over every edited region and fixed three contradictions introduced across passes: pass 1's §2.5 step-4 USD enumeration missing `affected_customer_count`; §3.12 ¶2 vs ¶3 disagreeing on which `measurement_basis` decides; and §3.12 ¶6's "decrements by 1" against the exact-restoration sentence. §3.10's satisfy paragraph was aligned with pass 2's §3.6 rescind clause on the cascade-satisfied flag. Pass-1 and pass-2 markers verified present after pass 3; heading count unchanged. No remaining edit contradicts another.

Orchestrator final verification: `PRD_COMPLETED.md` 501 lines / 122,061 chars, md5 `a765cf6f257acb240984fa282940fb96` — distinct from `PRD.md`/`PRD_FINALIZED.md` (`6c6f3cccdf2935ac86412e7126d98324`), confirming the scan actually ran rather than emitting a copy. `results.{1..8}.json` in `workspace/implementation/` all read `passed 136 / total 136 / failed 0`. Step 9 is the last step; the pipeline is complete.
