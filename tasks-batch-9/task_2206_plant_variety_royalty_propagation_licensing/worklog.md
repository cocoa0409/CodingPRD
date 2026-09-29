# Worklog — task_2206_plant_variety_royalty_propagation_licensing

## Step 1: Create task directory — 2026-09-01T00:29:09.794Z

Created `tasks/task_2206_plant_variety_royalty_propagation_licensing/` and `tasks/task_2206_plant_variety_royalty_propagation_licensing/workspace/`.

## Step 3: Copy shared files — 2026-09-01T00:31:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (verified byte-identical to project-root `INSTRUCTION.md`, 53 lines). Note: performed by the crashed run out of order; re-verified on resume.

## RESUME AUDIT — 2026-09-01T12:00:00.000Z

Resume-mode artifact audit of the task directory found only `worklog.md` and `workspace/INSTRUCTION.md` on disk. Missing: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`. Pipeline resumes at Step 2 (scaffold generation).

## RESUME AUDIT #2 — 2026-09-01T12:40:00.000Z

Second crash occurred during Step 2. Audit on this resume:

- `worklog.md` — present.
- `workspace/INSTRUCTION.md` — VALID (53 lines, byte-identical to project-root `INSTRUCTION.md` via `diff`). Step 3 confirmed complete; not redone.
- `SCAFFOLD.yaml` — **TRUNCATED / INVALID** (1080 lines). Parses as YAML but only contains top-level keys `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines`; the file cuts off mid-`state_machines` with §1.3 `calculations`, §1.4 `validations`, §1.5 `api_endpoints`, §1.6 `error_catalog`, §1.7 `rbac` entirely absent. Treated as missing per resume instructions.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` — absent.
- `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md` — absent.

Pipeline resumes at Step 2 (full scaffold regeneration, all three artifacts). Steps 1 and 3 are not redone.

## Step 2: Generate scaffold — 2026-09-01

All three artifacts regenerated from scratch and written incrementally (chunked heredoc appends, YAML re-parsed after every chunk) to avoid the truncation that killed the two earlier runs.

- `SCAFFOLD.yaml` — 3298 lines, 13 top-level keys (`scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`). Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`. Counts: 14 entities, 12 state machines, 3 concurrency rules, 9 calculations, 40 validations, 76 endpoints, 54 errors, 5 roles. `difficulty_level: beyond_expert`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1801 lines, single top-level key, all 9 §0.5 difficulty rules, 19 instances (≥2 differentiated per rule).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4290 lines, single top-level key, all 9 claim-extraction-guide sections, 93 instances (72 full recipes + 21 `excluded_because` stubs citing §1.8 instances).

Verification: `scaffold_lint.py` → `VERDICT: clean lint` (848 calls scanned, 91 instances). All 54 error ids are triggered or asserted somewhere in §1.8/§1.9. No forbidden concurrency vocabulary. `scenario` byte-identical to the assigned description. Instance names unique across the union of both design files.

Pipeline advances to Step 4 (PRD generation).

## Step 4: Generate PRD — 2026-09-01T13:15:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **612 lines**, written incrementally in 6 appends, ends cleanly on the final row of the §5 error table.

**Section list**
- `# Plant Variety Royalty & Propagation Licensing API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Record Identity, Timestamps and Version Counters · 2.5 The Logical Clock and the Deterministic Time Sweep · 2.6 Money, Rates and Rounding Discipline · 2.7 Stale-View Rejection on Repeatable Child Writes · 2.8 Path Resolution and the Order of Rejection · 2.9 Parallel State Dimensions, Cascades and Version Propagation · 2.10 Segregation of Duties on the Licensing Desk · 2.11 Compliance Scoring and Automatic Suspension
- `## 3. Business Logic & Workflows` — 3.1 Registering a Variety and Filing for Protection · 3.2 The Maintenance Calendar · 3.3 The Brand Dimension · 3.4 Regional Trialing, Evaluation Scoring and Commercial Release · 3.5 Propagators, Head Licences and the Suspension Cycle · 3.6 Production Quotas, Traceability Tags and the Committed-Unit Invariant · 3.7 Royalty Reporting: from the Reported Basis to the Booked Amount · 3.8 Sublicensing to Nurseries and Retail Programmes · 3.9 Enforcement: Surveillance, Genetic Testing, Audits and the Damages Waterfall
- `## 4. Endpoint Definitions` (4-column table) · `## 5. Error Code Catalogue` (2-column table)

**Coverage self-audit (machine-verified with a diff script against SCAFFOLD.yaml)**
- Endpoints: **76/76** in the §4 table (paths matched exactly); each also reachable in §2/§3 prose via state-transition, role+verb or capability framing.
- Error IDs: **54/54** in the §5 table, and **54/54** also referenced by name in §1–§3 prose.
- Validations: **40/40** — every validation's `error_id`, HTTP status, check semantics and `applies_to` scope placed (priorities 1–10 in §2.8's rejection ladder, 11–40 across §2.10/§2.11 and §3.1–§3.9).
- Calculations: **9/9** (`trial_performance_index`, `variety_protection_posture`, `annuity_total_due`, `effective_royalty_rate`, `royalty_report_totals` incl. both variants, `propagator_compliance_score`, `damages_waterfall`, `quota_tag_inventory`, `propagator_royalty_ledger`) — all constants, pinned rounding orders, tie-break orderings and both conservation invariants (I1 tag inventory, I2 royalty ledger) in prose.
- State machines: **12/12**, all **58** transitions described including the 3 server-chosen forks, 3 cycles, 2 parallel dimension pairs and every system-raised transition.
- Entities: **14/14** field lists; concurrency rules **3/3**; roles **5/5**.

**Hard contracts**
- Contract 1 (Field-Name Coverage): **PASS** — 0 missing of all `entities[].fields[].name`, all endpoint `input` identifiers (incl. optional filters and the three `expected_*_version` fields), and all path params, each appearing verbatim in backticks.
- Contract 2 (Rule Coverage): **PASS** — priorities, OCC triples, cascade levels with causes, `applies_to` scopes, field defaults/initial values and sibling-branch symmetry all present.
- Contract 3 (§3 Path Purity): **PASS** — 0 backticked tokens in §3 starting with `/`, 0 bare HTTP methods, 0 method+path combinations (also verified clean in §1–§2).

Note on one scaffold internal inconsistency: `RoyaltyLineItem.overrun_flagged`'s field description ("audited `billable_units` exceeds `allocated_units`") contradicts the `royalty_report_totals` formula (`tags_activated_units > reported_units`). I wrote the operative calculation formula version, since that is the computation the implementer must reproduce. No forbidden file was opened: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never read or grepped, and no sibling task directory was accessed.

Pipeline advances to Steps 5 + 6 (launched concurrently).

## Step 6: Generate implementation — 2026-09-01T14:00:00.000Z

Implementation complete and verified.

## Modules (all under `workspace/implementation/`)

| File | Lines |
|---|---|
| `app.py` (factory, 9 blueprints, `/health`, error handlers) | 83 |
| `store.py` (in-memory `Store`, 14 collections, logical clock) | 144 |
| `errors.py` (54 error IDs -> status + message) | 132 |
| `validation.py` (spec factories, body/query validation) | 228 |
| `middleware.py` (auth + `endpoint` decorator) | 66 |
| `response.py` (envelope, `api_request_id`, Decimal->JSON) | 83 |
| `calculations.py` (9 calculations) | 155 |
| `derive.py` (re-aggregation + cascades) | 429 |
| `common.py` (FK resolution, ladder helpers) | 119 |
| `routes/varieties.py` | 182 |
| `routes/filings.py` | 185 |
| `routes/trials.py` | 196 |
| `routes/propagators.py` | 187 |
| `routes/quotas.py` | 180 |
| `routes/royalty.py` | 243 |
| `routes/sublicense.py` | 134 |
| `routes/enforcement.py` | 278 |
| `routes/clock.py` | 93 |
| `routes/__init__.py` | 1 |
| `start.sh`, `requirements.txt` | 8, 1 |
| **total** | **3127** |

## Conformance

- **Endpoints: 76/76.** `app.url_map` reports 77 rules = the 76 PRD-table endpoints plus `/health`; no extras.
- **Errors: 54/54.** `ERROR_STATUS` and `ERROR_MESSAGE` each hold exactly 54 `ERR_*` entries, statuses matching PRD §5.
- **Calculations: 9/9** in `calculations.py` (regional performance index, effective royalty rate, annuity total, billable units/overrun, provisional & final report totals, late fee, compliance scoring, damages waterfall, serial prefix) — all `Decimal` + `ROUND_HALF_UP`, no floats for money.
- **State machines: 12/12**, including the parallel dimensions (variety lifecycle x brand, report review x settlement), the 3 cyclic machines (filing annuity laps, agreement suspend/reinstate laps, report dispute/revision laps), server-chosen fork on `conclude-testing` and payload-selected fork on engagement `finalize`.
- **Concurrency: 3/3** OCC guards (`expected_quota_version`, `expected_report_version`, `expected_agreement_version`) — all mandatory, checked after existence/ownership and before state checks, 412 on mismatch.
- **Roles: 5**, role lists per endpoint match SCAFFOLD.yaml exactly.
- **Storage:** dicts only. Grep confirms no `sqlite`, `open(`, `json.dump`, `pickle`, `/tmp` writes, and no `datetime.now`/`utcnow`/`time.time` — time comes solely from the logical clock (`2026-08-01T00:00:00Z`, advanced only by `POST /_clock/set_current_utc`). Nothing is seeded at startup.

## Boot verification

```
python3 -m compileall -q .   -> COMPILE_OK
PORT=8731 bash start.sh &    -> boots
curl /health                 -> 200
after kill                   -> 000 (server down)
```

`start.sh` reads `$PORT`, `app.run(host="0.0.0.0", ..., use_reloader=False)`, and `exec`s Python in the foreground, so the harness can kill/relaunch per test.

## Functional testing

Two smoke suites both pass with 0 failures: an HTTP suite against the live server (variety -> protection -> trials -> release -> brand -> agreement -> quota -> tags -> report accept/settle -> sublicense -> surveillance -> audit -> clock sweep -> pagination/auth negatives) and an in-process suite covering the remaining paths (site capacity aggregate with adjacency-is-not-overlap, annuity ladder incl. `ERR_ANNUITY_AMOUNT_MISMATCH` and 3% volume credit, tag void/reconcile invariant `allocated == available + committed`, late report -> accept -> dispute -> revise -> resubmit -> accept -> settle -> reverse with ledger conservation, suspend/thaw/reinstate laps, `ERR_COMPLIANCE_SCORE_TOO_LOW` on reinstatement after a MATERIAL finding, terminate cascade, `NO_MATCH` and `NONE` forks, grant revoke, `PROTECTION_LAPSED` cascade then retire, brand register/renew/abandon, grace-expiry clock sweep counters, and rolling-120-day score recovery).

Three fixes were applied during this pass, all in test expectations rather than the implementation except two earlier scaffold-driven changes to `routes/enforcement.py` (`sampled_unit_count` required `Int(1)`; `CASE_SCHEMA` field order aligned to the scaffold so body-FK resolution order matches).

## Step 5: Generate unit tests — 2026-09-01T14:55:00.000Z

All queues are complete and the mandatory verification passes.

## Deliverables

**`test_helpers/` (Stage 1, 9 files)** — `types.py`, `api_client.py` (76 endpoint methods over `GenericApiClient`), `api_errors.py` (54-member `ApiErrorId` + HTTP status map), `constants.py`, `test_users.py` (5 roles; `Propagator` is the one entity-backed identity), `factories.py` (24 payload factories), `fixtures.py` (protection / trial / licensing / royalty / audit / surveillance chains), `assertions.py`, `__init__.py` barrel.

**`test_suite/` (Stage 2, `conftest.py` + 26 concern files, 237 tests)** — files 01–08 carry queue A (depth), 09–26 carry queue B (breadth), each file >=5 tests, grouped by testing concern with domain-language class and test names.

Files added this session: `test_24_role_boundaries_and_shared_surfaces.py` (16), `test_25_stale_parent_views_and_derived_counters.py` (13), `test_26_derived_state_is_current_in_the_same_response.py` (6).

## Coverage

- **Queue A (§1.8 difficulty):** 9 rules / **19 instances — 19 translated, 0 skipped**, every instance carrying >=2 tests.
- **Queue B (§1.9 corner):** 9 sections / 93 instances. **All 72 non-stub instances translated (>=1 test each)**; the 21 `excluded_because` stubs were correctly not translated (audit confirms none is tagged).
- **No instance was dropped by the PRD-first filter.** Three *assertions inside* otherwise-translatable recipes were omitted because the PRD contradicts or does not derive them: (a) the `errors` recipe's claim that an *unrecognised* role returns `ERR_UNAUTHENTICATED` — PRD §2.1/§2.8 step 2 give `ERR_FORBIDDEN_ROLE`; (b) the `endpoints` recipe's "no update or delete endpoint exists for Propagator" — not assertable over HTTP; (c) the `line_item_create_with_a_stale_report_version` recipe's claim that `provisional_total_cents` is 3500 while the report is still `DRAFT` — PRD §3.7 states line money is computed at submission, so the 3500/10500 divergence is asserted at submission instead.

## Audits

- Tagging: `total tests: 237`, `untagged/dual: []`, `unknown tags: []`, `difficulty with <2 tests: 0`, `corner live with 0 tests: 0`, `stub instances wrongly tagged: []`.
- Citations: every `PRD x.y: "..."` quote verified verbatim against `workspace/PRD.md` (whitespace-normalized) — `missing: 0` across all 26 files. Six invented citations found earlier and two more in `test_24` (a fabricated clock sentence and a fabricated countersignature sentence) were replaced with exact PRD text.
- `grep -rin scaffold test_suite test_helpers` -> no matches.

## Verification output

```
$ python3 -m compileall -q test_helpers test_suite && python3 -m pytest test_suite --collect-only -q | tail -20
... (collected node ids) ...
237 tests collected in 0.63s
```

Zero collection errors.

Pipeline advances to Step 7 (test/fix iteration loop).

## Step 7: Run tests and iterate — 2026-09-01T16:05:00.000Z

All 8 parallel rounds now pass 237/237.

```
Round 1: 237/237   Round 5: 237/237
Round 2: 237/237   Round 6: 237/237
Round 3: 237/237   Round 7: 237/237
Round 4: 237/237   Round 8: 237/237
```

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (sweep 1: 220/237 in all 8 rounds, union = 17 failures, zero flakiness; sweep 2 after fixes: 237/237 in all 8 rounds).

**Tests deleted:** none. One assertion was removed under STEP 1c partial coverage (see below); no whole test lost coverage.

**Fixes applied to `test_helpers/`:** none — every root cause lived in `test_suite/` assertions or in per-test setup helpers defined inside the test files themselves.

**Fixes applied to `implementation/`:** none. Every one of the 17 failures was a test-layer defect; in each case the implementation was the PRD-faithful side.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_05_compliance_scoring_and_audit_findings.py` — `TestReinstatementReportsTheScoreGateFirst._propagator_failing_both_gates`: `period_end` 2026-11-01 -> 2026-08-05. The setup posted `due_at` (2026-08-10) *before* `period_end`, which PRD §3.7 rejects with `ERR_INVALID_INTERVAL`; 3 tests died in setup. New value keeps the period inside the agreement term and keeps submission at 2026-08-15 strictly after `due_at`, so `is_late` intent is preserved.
2. `test_suite/test_14_royalty_totals_and_late_fee.py` — `TestTheLateFeeIsTakenOnTheAuditedTotal._submitted_late`: same `ERR_INVALID_INTERVAL` setup bug, same fix (3 tests).
3. `test_suite/test_15_compliance_input_set_and_window.py` — `TestASubmittedLateReportIsOutsideThePenaltySet._submitted_late_report`: same `ERR_INVALID_INTERVAL` setup bug, same fix (3 tests).
4. `test_suite/test_18_temporal_windows_and_the_clock.py` — `test_one_second_forward_is_enough_to_be_accepted`: `current_utc` compared by string spelling -> `assert_instant_equals`. PRD §2.5 pins the *instant* the clock lands on; the three-fractional-digit format is pinned only for `api_request_timestamp`/`created_at`/`updated_at` (§2.2, §2.4), so spelling is not derivable, the instant is.
5. `test_suite/test_24_role_boundaries_and_shared_surfaces.py` — `test_any_role_may_move_the_clock` and `test_the_clock_advances_once_under_each_capacity_in_turn`: same `current_utc` spelling -> `assert_instant_equals` (2 tests).
6. `test_suite/test_02_trial_scoring_and_site_capacity.py` — `test_one_passed_region_is_not_enough_to_release`: expected `ERR_RELEASE_CRITERIA_NOT_MET` (422) -> `ERR_INVALID_STATE_TRANSITION` (409), plus an added assertion that the variety is still `IN_TRIAL`. `TRIAL_COMPLETE` is reachable only when `passed_trial_region_count` hits 2 (§3.4), so with one passed region release's only declared origin state is never entered, and §2.8 rung 9 fires before the business-tier release gates.
7. `test_suite/test_18_temporal_windows_and_the_clock.py` — `test_one_second_later_the_sweep_has_already_taken_the_filing`: expected `ERR_INVALID_STATE_TRANSITION` -> `ERR_TERMINAL_STATE` (both 409). §2.8 rung 8 lists "a filing that is `LAPSED` or `ABANDONED`" as terminal and runs *before* the generic transition check.
8. `test_suite/test_26_derived_state_is_current_in_the_same_response.py` — `test_the_retire_response_reports_the_terminal_lifecycle_and_its_instant` -> renamed `..._reports_the_terminal_lifecycle`; dropped the `retired_at` assertion (STEP 1c partial coverage, category: **PRD silence — field never named**). PRD mentions `retired_at` nowhere; §3.1's null list stamps `released_at` only and §3.4 retirement stamps no instant. The covered assertion (`lifecycle_state == "RETIRED"`) is kept.
9. `test_suite/test_10_lifecycle_transitions.py` — `test_the_owning_variety_is_re_derived_to_pending`: variety `version` 2 -> 3, with an added intermediate assertion that the draft filing already carried the variety to `PENDING`/version 2. §2.4 states "A recomputation of a derived field is a mutation... The same holds for a variety whose protection posture ... is re-derived"; opening the first DRAFT filing moves the posture `UNPROTECTED -> PENDING` (a change the suite itself asserts in `test_17`), and §3.1 then forces a second bump on lodging even though the posture is unchanged.
10. `test_suite/test_13_damages_waterfall.py` — `test_a_zero_residue_credits_nothing_and_touches_no_propagator` -> renamed `..._credits_nothing_to_the_named_suspect`; propagator `version` unchanged -> `+ 1`. §3.9 conditions the bump on *naming a suspect*, not on a non-zero credit ("When the case names a `suspected_propagator_id`, ... the propagator's `version` increments by 1; with no named suspect no credit is applied and no propagator is touched"), and where the PRD wants the no-actual-change carve-out it says so explicitly, as in §3.8 revocation ("the variety's `version` increments only when the count actually changed").

No assertion was weakened: the two error-id changes replace a wrong code with the code the §2.8 rejection ladder pins, no `skip`/`xfail` was added, no boundary was made approximate, and no implementation check or field was added, removed, or relaxed. Sweep artifacts are in `workspace/implementation/results.1..8.json`.

Step 8 is NOT skipped: although `implementation/` and `test_helpers/` fixes were both 0, there were 10 `test_suite/` fixes and 1 assertion removal, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) does not hold.

## Step 8: Finalize PRD — 2026-09-01T16:20:00.000Z

`PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 612 lines; `PRD_FINALIZED.md`: 612 lines; **%-delta 0.0%** (4 in-place line revisions, no lines added or removed, no new sections).

## Changes (one bullet each)

- **§2.5 (clock capability response)** — revise — pinned that the `current_utc` the clock endpoint returns is the instant the clock now holds, rendered in the §2.4 three-fractional-digit ISO 8601 UTC form — `implementation/routes/clock.py:88` (`store.now_iso()`) via `implementation/store.py:99` -> `store.py:21-27` (`fmt_dt`, `TS_FMT[:-3] + "Z"`).
- **§3.1 (Filing for protection, new-filing initial state)** — insert — opening a filing also re-derives the parent variety's `protection_posture`/`protected_jurisdictions`, and on *this* operation the variety's `updated_at`/`version` move only when the derivation actually changed one of them (first filing: `UNPROTECTED -> PENDING`) — `implementation/routes/filings.py:69` (`recompute_protection(variety)`, un-forced) + `implementation/derive.py:70-75`, `derive.py:25-35`.
- **§3.1 (How protection posture is derived, trigger list)** — revise — added "on opening a filing" to the list of re-derivation triggers (list previously read as status-changes only) — `implementation/routes/filings.py:69`.
- **§3.4 (Retirement)** — insert — retirement stamps no instant of its own; there is no retirement timestamp field, and `released_at` is untouched — `implementation/routes/varieties.py:127` (`apply(variety, {"lifecycle_state": "RETIRED"}, force=True)`).

## Per-edit pre-edit search log

**Edit 1 — §2.5 `current_utc` rendering** (step_7 items 4, 5)
- (a) Subject: the textual spelling of instants the server emits, specifically the clock endpoint's `current_utc`.
- (b) Paths enumerated: `grep -rn "now_iso()" implementation/` -> every server-stamped instant (`store.py:108/110/116` for `created_at`/`updated_at`; `trials.py:171` `evaluated_at`; `enforcement.py:158/251/260` `concluded_at`/`finalized_at`; `propagators.py:115` `countersigned_at`; `quotas.py:144` `issued_at`; `royalty.py:151/169` `submitted_at`/`accepted_at`; `sublicense.py:117` `activated_at`; `varieties.py:115/151/170` `released_at`/`brand_registered_on`; `filings.py:90/102/171` `filed_on`/`granted_on`; `response.py:25` `api_request_timestamp`; `clock.py:88` `current_utc`) all route through `store.fmt_dt` (3 digits + `Z`). Also checked the *client-supplied* instant fields, which are stored **verbatim** from the payload and never normalized (`royalty.py:58-61` `period_start`/`period_end`/`due_at`; `filings.py:134` `annuity_due_date`; `varieties.py:150/169` `brand_renewal_due_at`; `store.py:30-46` `parse_dt` is parse-only).
- (c) Adjustment: deliberately scoped the sentence to `current_utc` alone and phrased it as "rendered like the server-stamped timestamps of §2.4". An earlier, broader phrasing ("every instant in this system is rendered with three fractional digits") would have been a false universal, since payload-supplied date fields are echoed back in whatever spelling the client sent.

**Edit 2 + Edit 3 — §3.1 variety re-derivation on filing creation** (step_7 item 9)
- (a) Subject: which filing operations re-derive the variety's protection fields, and when the variety's `version` moves.
- (b) Paths enumerated via `grep -rn "recompute_protection\|protection_values\|protection_posture" implementation/`: `filings.py:69` create (un-forced -> bump only if changed), `filings.py:93` file, `:105` grant, `:117` abandon (all `force=True` -> always bump, matching PRD §3.1's existing "every one of them also ... increments the variety's `version`"), `filings.py:143` schedule-annuity and `:175` pay-annuity (un-forced -> no bump, since `MAINTENANCE_DUE` and `GRANTED` are the same posture branch — matching §3.2, which claims no variety bump for either), `derive.py:365-383` `lapse_filing` (forced, combined with `active_sublicense_count` as a single mutation), and `clock.py:28` sweep grace-expiry which reuses `lapse_filing`. Also read `derive.py:25-35` `apply()` to confirm the un-forced no-op semantics, and `varieties.py:77` for the `UNPROTECTED` seed.
- (c) Adjustment: bounded the "only when the derivation actually changed" claim with "on this operation" so it cannot be read back onto the forced bumps of `file`/`grant`/`abandon`/lapse; and in the trigger list I only widened membership ("a filing joins it or changes status") without attaching any version claim, so schedule-annuity and pay-annuity (re-derive, no bump) stay correctly described.

**Edit 4 — §3.4 retirement timestamp** (step_7 item 8)
- (a) Subject: what the retire transition writes on the variety, and whether any retirement instant exists.
- (b) Paths enumerated: `grep -rn "retired_at" implementation/` -> zero hits anywhere; `grep -rn "RETIRED" implementation/` -> only `varieties.py:37` (constant), `varieties.py:127` (the sole writer, sets `lifecycle_state` only), and `trials.py:125` (a read-only terminal guard on planting). Also re-read `varieties.py:65-89` (create) to confirm no such key is ever seeded, and `varieties.py:113-117` (release) to confirm `released_at` is written only there.
- (c) Adjustment: stated it as "carries no retirement timestamp field at all" rather than "`retired_at` is null", because the field does not exist in the serialized record (`response.py:39` serializes the stored dict as-is), and asserting a null field would itself be a new mismatch.

## Items deliberately left unpatched (PRD already determines them)
- Items 1–3 (`ERR_INVALID_INTERVAL` fixture bugs): §3.7's "`due_at` must be at or after `period_end`" exactly matches `royalty.py:50` (`due_at < period_end`). Pure test-setup defect.
- Item 6 (release from `IN_TRIAL` -> `ERR_INVALID_STATE_TRANSITION`): §2.8 rung 9 plus §3.4's declared origin `TRIAL_COMPLETE -> RELEASED` already fix this; `varieties.py:108` runs `transition()` before the criteria check at `:109`.
- Item 7 (`ERR_TERMINAL_STATE` on a `LAPSED` filing): §2.8 rung 8 already lists `LAPSED`/`ABANDONED` as terminal and orders it before rung 9; `filings.py:151-152` matches.
- Item 10 (propagator `version` +1 on a zero-residue resolve with a named suspect): §3.9 already pins the bump to *naming a suspect*; `enforcement.py:186-191` uses `force=True` under exactly that condition.

Pipeline advances to Step 9 (full PRD-vs-implementation completeness scan).

## Step 9: Complete PRD — 2026-09-01T16:45:00.000Z

Done. `PRD_COMPLETED.md` is written, complete and non-truncated.

## Verification
- `workspace/PRD_FINALIZED.md`: **612 lines / 123,694 chars**
- `workspace/PRD_COMPLETED.md`: **612 lines / 136,161 chars** -> **+12,467 chars**, line count identical (every patch was an in-paragraph insert or revision; no new sections, no new paragraphs)
- §5 table intact: 54 `ERR_*` rows in both files; final row `| `ERR_NOTHING_TO_SETTLE` | 422 |` present as the last table line
- Endpoint table unchanged in shape: 76 impl `@endpoint` registrations vs 76 §4 rows, `METHOD path` lists diff `IDENTICAL`, role columns match

## Counts
**45 changed lines / 44 diff hunks — 35 ambiguity-pins, 10 mismatch-revisions.**

## Changes
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `implementation/response.py:18`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock, so it repeats verbatim while the clock stands still — `implementation/response.py:22`
- §2.3 — insert — ambiguity — non-integer / out-of-range `limit`, negative `offset` -> `ERR_INVALID_REQUEST`; empty-string value = omitted — `implementation/validation.py:190`
- §2.3 — insert — ambiguity — identical `created_at` is normal (clock stands still); final tiebreak is insertion order, never `id` — `implementation/store.py:121`
- §2.3 — insert — ambiguity — filters compare raw strings, empty = absent, undeclared query params ignored; `overrun_flagged` accepts true/1/yes, false/0/no — `implementation/common.py:109`, `implementation/validation.py:222`
- §2.4 — insert — ambiguity — underscore-prefixed internal fields (`_seq`, `_concluded_result`) are stripped from every response — `implementation/response.py:29`
- §2.4 — revise — mismatch — a re-derivation that changes nothing is not a mutation, so `version`/`updated_at` do not move — `implementation/derive.py:25`
- §2.5 — insert — ambiguity — `compliance_recompute_count` counts every propagator visited, not those changed; the five keys are the whole `data` object — `implementation/routes/clock.py:69`
- §2.6 — insert — ambiguity — decimals serialize as bare JSON numbers, fixed-scale trailing zeros not preserved on the wire — `implementation/response.py:29`
- §2.6 — revise — mismatch — 4-dp inputs accept **at most** 4 dp (normalized up), not exactly 4 — `implementation/validation.py:87`
- §2.7 — insert — mismatch — carve-out: line-item create *does* have a `DRAFT` precondition, but it sits after the OCC guard; explicit `null` for an `expected_*` field is a 400 — `implementation/routes/royalty.py:95`
- §2.8 — insert — ambiguity — rung-3 detail: `null` = omitted, ints reject bools/fractions, decimals accept numeric strings, code charsets, non-object JSON rejected, absent body = `{}` — `implementation/validation.py:116`
- §2.8 — insert — ambiguity — enumerates the timing/companion-dimension gates that answer `ERR_INVALID_STATE_TRANSITION` — `implementation/routes/propagators.py:106`, `implementation/routes/sublicense.py:114`
- §2.9 — insert — ambiguity — where §3 pins an increment outright it lands unconditionally (`force=True`) — `implementation/derive.py:25`
- §3.1 — insert — ambiguity — filing creation is not gated on variety lifecycle, `RETIRED` included — `implementation/routes/filings.py:40`
- §3.2 — insert — ambiguity — the 90-day grace default is re-applied every lap, resetting a narrower earlier window — `implementation/routes/filings.py:123`
- §3.2 — insert — ambiguity — posture re-derivation on schedule-annuity is non-forced, so the variety does not bump — `implementation/routes/filings.py:123`
- §3.2 — insert — ambiguity — same on pay-annuity, and it never changes anything because `MAINTENANCE_DUE`/`GRANTED` share a posture branch — `implementation/derive.py:54`
- §3.3 — insert — ambiguity — brand-renew requires both fields; `brand_registry_class` is not restatable (unknown field) — `implementation/routes/varieties.py:158`
- §3.4 — insert — ambiguity — `occupied_plot_count` refreshed only on schedule/plant/certify, stale between evaluate and certify; the capacity rule re-counts live — `implementation/routes/trials.py:154`
- §3.4 — insert — ambiguity — scheduling a trial refreshes site occupancy, so the site bumps on scheduling too — `implementation/routes/trials.py:73`
- §3.4 — insert — ambiguity — planting into a `RETIRED` variety is `ERR_TERMINAL_STATE`, ordered after the trial's own gates and before the date check — `implementation/routes/trials.py:120`
- §3.4 — revise — mismatch — `propagation_pass_rate` accepts at most 4 dp — `implementation/routes/trials.py:154`
- §3.4 — revise — mismatch — certification promotes the lifecycle only when the variety is currently `IN_TRIAL`; the version bump is unconditional — `implementation/routes/trials.py:177`
- §3.5 — insert — ambiguity — duplicate `legal_name` (post-trim) -> `ERR_INVALID_REQUEST` 400, no dedicated code — `implementation/routes/propagators.py:37`
- §3.5 — insert — ambiguity — countersigning past `term_end` -> `ERR_INVALID_STATE_TRANSITION` 409 — `implementation/routes/propagators.py:106`
- §3.5 — insert — ambiguity — reinstatement's term check is evaluated last of three, after both eligibility gates, and returns 409 — `implementation/routes/propagators.py:133`
- §3.6 — insert — ambiguity — quota allocation consults nothing about the variety; gate order agreement-active -> territory -> uniqueness — `implementation/routes/quotas.py:40`
- §3.6 — insert — ambiguity — tag-order create order: ownership -> OCC -> `CLOSED` terminal -> frozen -> agreement-active — `implementation/routes/quotas.py:85`
- §3.6 — insert — ambiguity — voiding is not gated on the quota (`FROZEN` or `CLOSED` both fine) — `implementation/routes/quotas.py:170`
- §3.7 — insert — ambiguity — report creation is not agreement-gated; check order ownership -> uniqueness -> intervals -> term containment — `implementation/routes/royalty.py:41`
- §3.7 — insert — ambiguity — a line item requires `review_status` `DRAFT` (409), after the OCC guard; then frozen -> agreement -> cross-check -> uniqueness — `implementation/routes/royalty.py:95`
- §3.7 — insert — ambiguity — `dispute_note` is <=500 chars and persisted nowhere; the two dimensions are one combined origin test, so `SETTLED`/`REVERSED` yields 409 not a terminal code — `implementation/routes/royalty.py:181`
- §3.7 — insert — ambiguity — revising touches no propagator field and does not bump the propagator — `implementation/routes/royalty.py:192`
- §3.7 — insert — ambiguity — `reversal_note` likewise <=500 chars and never persisted — `implementation/routes/royalty.py:232`
- §3.8 — insert — ambiguity — proposing a grant is not gated on agreement status at all; check order OCC -> territory -> interval -> term — `implementation/routes/sublicense.py:31`
- §3.8 — revise — mismatch — "Four business conditions" -> five, evaluated in the stated order; closed expiry window fails with `ERR_INVALID_STATE_TRANSITION` 409 after protection/release and before exclusivity — `implementation/routes/sublicense.py:114`
- §3.8 — revise — mismatch — exclusivity is the fifth and last condition, not the fourth — `implementation/routes/sublicense.py:115`
- §3.9 — revise — mismatch — `sampled_unit_count` is **required**, not "at least 1 when supplied" — `implementation/routes/enforcement.py:27`
- §3.9 — revise — mismatch — `match_confidence` accepts at most 4 dp — `implementation/routes/enforcement.py:34`
- §3.9 — insert — ambiguity — opening an engagement is not gated on the report's review/settlement status nor the agreement's status; `agreement_id` resolves first — `implementation/routes/enforcement.py:198`
- §3.9 — insert — ambiguity — the `underreported_units >= 1` rule is judged in the body tier ahead of path resolution, so it beats a nonexistent/terminal engagement — `implementation/routes/enforcement.py:239`
- §4 — insert — ambiguity — trailing slashes tolerated; the 22 payload-free transition endpoints reject any body field with 400; `GET /health` is an unauthenticated probe returning `{"status":"ok"}` outside the envelope — `implementation/middleware.py:59`, `implementation/app.py:38`, `implementation/app.py:43`
- §4 — revise — mismatch — brand-renew restates the mark text as a **required** field (was "optionally") — `implementation/routes/varieties.py:158`
- §5 — insert — ambiguity — framework-level `ERR_NOT_FOUND` 404 (unrouted path), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 sit outside the catalogue, use the same envelope, and precede authentication — `implementation/app.py:51`

Notable substantive findings surfaced while walking the implementation: `occupied_plot_count` is genuinely stale between a trial's evaluation and its certification (the capacity check recomputes live instead of reading it), the §2.7 claim that "no state precondition would otherwise reject the second create" was false for royalty line items, and §3.8 shipped with an internal off-by-one in its condition count.

Pipeline complete through Step 9.
