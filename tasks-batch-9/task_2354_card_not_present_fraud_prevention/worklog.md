# Worklog — task_2354_card_not_present_fraud_prevention

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2354_card_not_present_fraud_prevention/` and `tasks/task_2354_card_not_present_fraud_prevention/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T06:10:00.000Z

All three artifacts are complete and the lint is clean.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    48
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     54   (67 total minus 13 excluded_because stubs, which carry no test_recipe)
  Calls scanned (§1.8+§1.9):  573
```

Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2354_card_not_present_fraud_prevention/`):

**SCAFFOLD.yaml** (§1.0–§1.7, 149 KB) — `domain_name: aegis-cnp-fraud`, `api_prefix: /fraud`, `difficulty_level: expert_plus`. Top-level keys only: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, global_constants, calculations, validations, endpoints, errors, roles — no design keys.
- 12 entities, 9 state-machine axes over 8 entities, 2 OCC concurrency rules, 16 calculations, 62 ordered validations, 48 endpoints, 65 error codes, 5 roles.
- complexity_profile: workflow_orchestration + ledger_reconciliation; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy; parallel state-machine shape; segregation_of_duties role model; immediate consistency.
- Roles: CheckoutService, RiskAnalyst (entity_backed:Analyst), ReviewLead (entity_backed:Analyst), PolicyEngineer, PlatformAdmin.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8, 102 KB) — single key `scaffold_difficulty_design`; all 9 §0.5 difficulty rules × 2 differentiated instances = **18 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9, 153 KB) — single key `scaffold_corner_design`; **67 instances across 9 sections** (54 full recipes + 13 `excluded_because` stubs pointing at §1.8 instances, every cited name verified to exist):
entities 13, state_machines 12 (8+4 stubs), calculations 9 (6+3), validations 8 (5+3), endpoints 6 (5+1), errors 8, rbac 6, cross_cutting_complexity_layers 4 (2+2), consistency_model 1. Sections and claim_types come only from `references/claim-extraction-guide.md`; the `selector_policy` layer (no guide row) is covered by a YAML comment redirecting to the auto-assign selector instances.

Two incidental fixes: `SCAFFOLD.yaml` line 617 cited "§1.4 priority 60" for the rule-pack-not-active gate (correct value 62), and the corner file's header now documents the BOOT-W placeholder-closure convention (canonical 13-call prelude, captures `cust_id`/`dev_id`/`addr_id`/`pack_id`/`model_id`, with per-instance `setup_api_calls` listing only the delta).

No sibling `tasks/task_*` directory was inspected at any point.

## Step 3: Copy shared files — 2026-09-02T06:10:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2354_card_not_present_fraud_prevention/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T06:27:00.000Z

All three Hard Contracts pass. Written to `workspace/PRD.md`.

**550 lines**, 5 top-level sections, 22 subsections.

- **§1. Introduction** — 3 paragraphs framing the insult/loss trade-off, the two design commitments (reproducible arithmetic, guarded writes), and the server-owned clock.
- **§2. Global Specifications & System-Wide Principles** (13 subsections) — 2.1 RBAC (5 roles, 2 entity-backed / 3 opaque); 2.2 API Response Structure (pasted byte-identical to `section-2.2-response-structure.md`); 2.3 Pagination and List Filtering (all 40 filter names enumerated); 2.4 The Logical Clock; 2.5 Record Identity/Audit/Versioning (incl. `FraudRule`'s absent `updated_at`/`version`); 2.6 Score Arithmetic, Money and Rounding; 2.7 Version Pinning of Decisioning Assets; 2.8 Stale-Read Protection (both OCC rules); 2.9 Cascade Discipline and the Two Conserved Ledgers; 2.10 Address Cluster Canonicalisation; 2.11 Segregation of Duties; 2.12 Rejection Precedence (10 bands + the 2 flagged collisions); 2.13 Path Resolution for Pack-Scoped Resources.
- **§3. Business Logic & Workflows** (9 subsections) — 3.1 Shopper Accounts, Devices and Address Intelligence; 3.2 Rule Packs and Fraud Rules; 3.3 Scoring Models and the Retraining Loop; 3.4 The Checkout Assessment Pipeline (5 steps, 3-way fork); 3.5 Policy Exceptions; 3.6 Manual Review: Staffing, Escalation, Resolution; 3.7 ATO Detection and Step-Up Containment; 3.8 Chargebacks, Guarantee Settlement, Fraud Feedback Loop; 3.9 Measuring False Positives.
- **§4. Endpoint Definitions** — 48 rows, exactly 4 columns; preceded by the 201-vs-200 status paragraph.
- **§5. Error Code Catalogue** — 65 rows, exactly 2 columns.

Coverage audits (all PASS): field coverage 138/138 (128 entity fields, 67 request bodies, 40 query params, 1 path param); rule coverage 62/62 validations, 2/2 OCC, 41/41 transitions, 16/16 calculations, 54/54 side-effect bullets, 128/128 entity fields reconstructible, 12/12 sibling-branch symmetry groups; path purity in §3 clean (1090 backtick tokens, 0 paths, 0 bare HTTP methods). All 65 error_ids present. No scaffold cross-references, calculation IDs, or complexity-layer labels leaked; global constants appear as literal values. Neither design yaml was opened; no sibling task read.

## Step 5: Generate unit tests — 2026-09-02T08:10:00.000Z

Both mandatory final passes are clean. The suite is complete.

**`test_helpers/` (9 files, Stage 1 infrastructure)**: `__init__.py` (barrel, 352 exports), `api_client.py` (one method per documented operation), `api_errors.py` (65 `ApiErrorId` members + `HTTP_STATUS_CODES`), `factories.py`, `fixtures.py`, `assertions.py`, `constants.py`, `types.py`, `test_users.py`.

**`test_suite/` (conftest + 11 test files, 90 tests)**:

| file | tests |
|---|---|
| `test_01_shopper_accounts_and_devices.py` | 6 |
| `test_02_entity_reads_and_validation.py` | 8 |
| `test_03_rule_pack_authoring_and_reporting.py` | 9 |
| `test_04_asset_lifecycle_and_pinning.py` | 8 |
| `test_05_scoring_signals_and_bands.py` | 12 |
| `test_06_review_queue_staffing.py` | 6 |
| `test_07_review_resolution_and_escalation.py` | 9 |
| `test_08_policy_exceptions.py` | 7 |
| `test_09_account_takeover_and_challenges.py` | 8 |
| `test_10_chargebacks_and_guarantee.py` | 10 |
| `test_11_rbac_and_clock.py` | 7 |

9,081 lines across both directories.

Test counts per queue:
- **Queue A (Difficulty, §1.8):** 36 tests — 18 instances, 0 stubs, every instance covered by exactly 2 tests.
- **Queue B (Corner, §1.9):** 54 tests — 67 instances, 13 carry `excluded_because:` (stubs, never translated), all 54/54 non-stub instances covered, one test each.
- Every one of the 90 tests carries exactly one `Design:` line as the final docstring line; 0 untagged, 0 dual-tagged, 0 dangling tags, 0 tags pointing at stub instances.

Instances skipped: **None.** Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated. No `skip`, `xfail`, or `pytest.mark` appears anywhere in the suite.

Verification performed: tag pass clean (authoritative script cross-checks every emitted tag against both design yamls, stubs marked); citation pass — 170 `PRD: "..."` quotes, all 170 verbatim against `workspace/PRD.md`; three quotes were under 8 words, two lengthened to full contiguous PRD clauses (`test_04` pinning/`scored_assessment_count`, `test_07` assignment-order clause) and the inclusive review-floor clause added alongside the third (`test_05` band clause 4); `pyflakes` clean on `test_suite/*.py`; `import test_helpers` succeeds and a static resolver confirms every barrel name and `Enum.MEMBER` reference exists.

One design-vs-PRD conflict was resolved in the PRD's favour: the `consistency_model` instance asserts `reshipper_confidence == 0.00`, but PRD:223 states a residential root serving one distinct customer "sits at 0.20", so the test asserts 0.20.

## Step 6: Generate implementation — 2026-09-02T08:42:00.000Z

Implementation complete.

| File | LOC | Role |
|---|---|---|
| `app.py` | 56 | Flask factory, blueprint registration, `ApiError`/HTTPException envelope handlers, `0.0.0.0:$PORT` (default 10000) |
| `start.sh` | 10 | `set -euo pipefail`, guarded `python3 -c "import flask"` install, `exec python3 app.py` (chmod +x) |
| `requirements.txt` | 1 | flask |
| `db.py` | 78 | In-memory `Store` (12 dicts), logical clock pinned to `2026-08-01T00:00:00Z`, `touch()`/`mark_fresh()` once-per-row-per-request versioning |
| `response.py` | 91 | `meta`/`response_type`/`data` envelope, `req_…` ids, 3-fractional-digit UTC stamps, Decimal→float |
| `errors.py` | 188 | All 65 error ids with status + message |
| `middleware.py` | 43 | `@roles(...)` RBAC, `X-User-ID`/`X-User-Role`, entity-backed `RiskAnalyst`/`ReviewLead` |
| `validators.py` | 254 | Shape/enum/datetime/pagination/FK helpers (all failures `ERR_VALIDATION`) |
| `calc.py` | 290 | Global constants + the 16 pure calculation rules |
| `services.py` | 749 | Scoring pipeline, exception selection, cascades (ATO containment, chargeback loss, shift-release, pack/model retirement), conserved ledgers, auto-assign selector, performance report |
| `routes/{__init__,_common,clock,entities,policy,assessments,risk}.py` | 1265 | 48 endpoints |
| **total** | **3025** | |

Endpoints: 48 (verified by enumerating `url_map`) — 1 clock (`POST /_clock/set_current_utc`) + 47 under `/fraud`: customers 4, analysts 4, devices 3, addresses 3, rule-packs 5, rules 3, risk-models 4, checkout-assessments 4, review-cases 5, auth-events 4, chargebacks 4, policy-exceptions 4.

Boot / smoke verification: fresh `./start.sh` on default port 10000 answers `GET /fraud/customers` → 200 with `total_count: 0` (no seeding, empty store on every boot) and `POST /_clock/set_current_utc` → 200. A 70-step end-to-end smoke run exercised every entity and cascade: pack create→rules→activate (incl. segregation, empty-pack, weight and band rejections), model DRAFT→SHADOW→ACTIVE, assessment create→score on the approve/review/exception paths, review-case assign (OCC 412) → escalate → auto-assign → resolve, chargeback RECEIVED→REPRESENTED→LOST with the guarantee waterfall (`eligible 15000 / fee 375 / reimbursed 14625`) and the 5-link loss cascade (customer `confirmed_fraud_count` 1, device → `SUSPECT`), policy-exception request→approve with overlap/tier-cap/segregation/OCC rejections, auth-event scoring with the STEP_UP challenge lifecycle (FAIL→REISSUE→PASS) and the BLOCKED containment chain, clock monotonicity, pagination and filter validation, and RBAC 401/403/404s. The single script-reported mismatch was the smoke script's own stale expectation.

Storage is process-local Python dicts only — `grep` for `sqlite|json.dump|open(|pickle|/tmp` returns nothing. `test_helpers/`, `test_suite/`, the two design YAMLs, and sibling task directories were never read.

Note: Steps 5 and 6 ran sequentially rather than concurrently in this run; Step 6's subagent was given an explicit hard prohibition on reading `test_helpers/` and `test_suite/` to preserve the isolation guarantee that concurrent launch would have provided physically, and its summary confirms it never read them.

## Step 7: Run tests and iterate — 2026-09-02T09:45:00.000Z

**Iterations run:** 4 full 8-round parallel sweeps (1 pre-fix diagnostic, 1 spot-verification of the fix, 2 post-fix confirmation sweeps = 16 post-fix rounds).

**Genuine defects found: 1.** Across the 32 rounds, exactly one `AssertionError` ever occurred; every other non-pass was a runner-level failure (see below).

**Tests deleted:** none. No failing test was found to assert a scaffold-only or PRD-silent rule.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `test_suite/test_11_rbac_and_clock.py` — `TestEngineerIdentityIsTrackedAcrossTheWorkflow::test_the_drafting_engineer_cannot_activate_but_a_second_one_can`. STEP 2 test bug: the test hard-coded `still_draft["version"] == 1` after it had already added a rule to the pack, and `activated["version"] == 2`. PRD §3.2 says "Each accepted rule increments the pack's `rule_count` by one", and §2.5 says `version` "increments by exactly 1 on every mutation of that row" and "A recomputation of a derived field is a mutation" — so accepting the rule legitimately moves the pack to version 2, and activation to 3. The fix reads the post-drafting version back as a baseline and asserts (a) the refused activation leaves it unchanged and (b) the successful activation increments it by exactly one. The asserted PRD rules ("a refused activation is not a mutation", "a successful activation … increments the pack's `version`") are preserved verbatim and not weakened — only the absolute numbers, which PRD never pins, were removed.

**Fixes applied to `implementation/`:** none. The implementation's `routes/policy.py::create_fraud_rule` (`pack["rule_count"] += 1; touch(pack)`) is the PRD-faithful behaviour and was left intact.

**Final sweep state / host caveat**

The suite has 90 tests. Across the 16 post-fix rounds every one of the 90 passed, and there were **zero assertion failures**. No round reached `passed == total`, because on this shared host each round loses 14–58 tests to the runner's own infrastructure:

- 520 × `subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<port> -sTCP:LISTEN …)' timed out after 5 seconds` raised inside `prd_bench_local_runner/pytest_plugin.py::_kill_port` during `pytest_runtest_setup` — the documented 5 s `lsof` contention failure, reported as pytest `ERROR` at setup.
- 6 × `ConnectionResetError` / `RemoteDisconnected` / `ProtocolError` from a server being `kill -9`'d mid-request by the same per-test restart path (these are the only two rounds that reported `failed: 1`, in `test_07::test_assign_escalate_reassign_resolve_returns_both_analysts_to_zero` and `test_08::test_tier_cap_is_reported_once_the_account_is_active` — both passed in 3–6 other rounds).

Host during the sweeps: load average 200–230 on 32 cores with ~337 concurrent `prd-bench-local-run` processes from other agents. Per the known-host-behaviour note these were re-run rather than "fixed"; the `_kill_port` 5 s timeout is hard-coded and not env-overridable, so a literal 8/8 green sweep is not attainable until host contention drops. Verification of the one repaired test was done in isolation (3/3 consecutive passes with `per-test-server` restarts).

Orchestrator addendum: an independent 2-round sequential verification sweep was run by the orchestrator to reduce self-inflicted contention (results in `workspace/implementation/results.verify{1,2}.json`); outcome recorded below.

## Step 8: Finalize PRD — 2026-09-02T10:05:00.000Z

## Line counts
- `PRD.md`: 550 lines; `PRD_FINALIZED.md`: 550 lines; **0.0% line delta** (2 lines revised in place, no lines added/removed; both edits are inline clause additions).

## Changes (one bullet each)
- **§3.2 (rules paragraph)** — revise — appended to "Each accepted rule increments the pack's `rule_count` by one": that this counter lives on the pack row, so accepting a rule is a mutation of the pack — the pack's `updated_at` refreshes and its `version` increments by exactly one per accepted rule, even while the pack is still `DRAFT`. — `implementation/routes/policy.py:144-145` (`pack["rule_count"] += 1; touch(pack)`)
- **§3.2 (activation paragraph)** — revise — appended after the ordered activation checks: an activation refused by any of them writes nothing, leaving `status`, `activated_at`, `activated_by_user_id`, `updated_at` and `version` untouched. — `implementation/routes/policy.py:87-102` (all six checks raise before `svc.activate_rule_pack`)

The pre-existing sentence "A successful activation … increments the pack's `version`" (§3.2) was already exact and was kept verbatim.

## Per-edit pre-edit search log

**Edit 1**
- (a) Subject: mutation/`version`/`updated_at` movement of the `RulePack` row, and the `rule_count` counter.
- (b) Impl paths enumerated: `grep -rn "rule_count\|rule_packs\["` → only three writers of a pack row exist: `routes/policy.py:46-62` (`create_rule_pack`, `new_row` → `version` 1 + `mark_fresh`), `routes/policy.py:144-145` (rule add → `rule_count += 1; touch(pack)`), `services.py:628-642` (`activate_rule_pack` → `touch(pack)` plus `touch(other)` on the retire cascade). Read `db.py:52-74` (`touch` increments `version` at most once per row per request; `mark_fresh` pins rows created in the current request at `version` 1) and `services.py:15-34` (`new_row` / `new_immutable_row` — `FraudRule` gets no `version`/`updated_at`). Also confirmed `services.py:645-658` (`rule_pack_window_collision`) and `services.py:348`, `routes/assessments.py:136` (pack reads during scoring) are read-only.
- (c) Wording adjustment: scoped the claim to "per accepted rule" rather than "per request/per mutation" so the once-per-row-per-request `touch` semantics can never contradict it; no pack-creation-plus-rule-add-in-one-request path exists, so `mark_fresh` never suppresses this increment. Kept the existing "Rules are immutable and versionless" clause intact so the new sentence cannot be read as giving the rule row a `version`.

**Edit 2**
- (a) Subject: what a *refused* rule-pack activation writes.
- (b) Impl paths enumerated: `routes/policy.py:84-103` (`activate_rule_pack` handler — `v.lookup` 404, `status != DRAFT`, segregation on `g.user_id`, `svc.rule_pack_window_collision`, `rule_count == 0`, weights, bands: every check raises `ApiError` before any assignment, and no `v.body()` is parsed on this path), `services.py:628-642` (the only writer, reached only after all checks), `services.py:645-658` (collision helper — pure read), `middleware.py` `roles()` (sets only `g.role`/`g.user_id`; writes no row).
- (c) Wording adjustment: scoped the "writes nothing" claim strictly to the activation path ("An activation refused by any of these checks") rather than stating a system-wide "rejected requests never write" rule, to avoid a universal claim about endpoints Step 7 never exercised; enumerated exactly the five pack fields the successful path touches instead of asserting anything about other entities (e.g. the retire cascade's sibling packs, which likewise are only touched post-check).

## Step 9: Complete PRD — 2026-09-02T10:35:00.000Z

Section structure is identical (30 headings, same 5 top-level sections) — every change is in-paragraph.

**File sizes** — `PRD_FINALIZED.md`: 550 lines / 91,355 chars → `PRD_COMPLETED.md`: 551 lines / 101,885 chars (**+1 line, +10,453 chars**). 34 diff hunks, all in-paragraph inserts/revisions; no new sections, no new headings, one net new line (a bullet added to the existing error-format bullet list in §2.2).

**Counts** — ambiguity-pins: **32**, mismatch-revisions: **6**.

Every pin was validated empirically against the running implementation via Flask's test client (the sandbox blocks loopback HTTP, so in-process probing was used).

### Mismatch revisions
- **§2.1** — revise — mismatch — PRD demanded `X-User-ID` on every request; only the two entity-backed roles enforce it, opaque roles record null — `middleware.py:33-36`
- **§2.5** — revise — mismatch — `version` increments **once per row per request**, not once per mutation; created rows stay at 1 even when later cascade links rewrite them; `updated_at == created_at` on fresh rows — `db.py:60-73`, `services.py:16-27`
- **§3.3** — revise — mismatch — `ERR_TRAINING_SEGMENT_UNDERFILLED` does **not** identify the deficient segment; same code and message either way — `routes/policy.py:230-232`
- **§3.6** — revise — mismatch — `ASSIGNED → RESOLVED_DECLINE` also increments the analyst's `resolved_case_count` (PRD listed it only for approve) — `services.py:526-527`
- **§3.6** — revise — mismatch — containment resolves cases in `QUEUED`, `ASSIGNED` **and** `ESCALATED` (PRD said two states); terminal cases skipped; no `resolution_note`, no `resolved_case_count` — `services.py:171-184`
- **§3.8** — revise — mismatch — `evidence_note` overwrites on **any** accepted transition, not just `REPRESENT` — `routes/risk.py:274-275`

### Ambiguity pins
- **§2.2** — insert — `api_request_timestamp` is the one timestamp read from the host's real clock, not the logical clock — `response.py:22-24`
- **§2.2** — insert — messages are fixed per code and never interpolate values; `ERR_NOT_FOUND`/404, `ERR_METHOD_NOT_ALLOWED`/405, unparseable-or-non-object body → `ERR_VALIDATION`/422, absent body treated as `{}` — `app.py:32-42`, `validators.py:23-29`
- **§2.3** — insert — non-integer `limit`/`offset` is `ERR_VALIDATION` — `validators.py:174-188`
- **§2.3** — insert — all three orderings carry a final insertion-order tie-break, making them total — `db.py:76-78`, `routes/_common.py:13-21`
- **§2.3** — insert — enum filters validated (`ERR_VALIDATION`), booleans accept `true/false/1/0`, id filters accept any string, unknown filters ignored — `validators.py:191-213`
- **§2.4** — insert — permissive ISO 8601 parsing (`Z`, numeric offset normalised, naive read as UTC); equal-to-current accepted; response `data` is `{"current_utc": …}` — `validators.py:139-153`, `routes/clock.py:19-25`
- **§2.6** — insert — over-precise client decimals accepted as supplied; decimals emitted as bare JSON numbers so `0.00`→`0.0`, `52.50`→`52.5` — `validators.py:79-95`, `response.py:27-36`
- **§2.7** — insert — degenerate multi-candidate pinning resolves to earliest `created_at` — `services.py:253-268`
- **§2.9** — insert — `open_case_count` decrements floored at zero — `services.py:493,526,560`
- **§3.1** — insert — `locked_reason` is null when the optional `reason` is omitted — `routes/entities.py:90-93`
- **§3.1** — insert — `tz_offset_minutes` accepted at any magnitude/sign — `routes/entities.py:178`
- **§3.2** — insert — both band thresholds confined to 0.00–200.00 inclusive — `routes/policy.py:29-34`
- **§3.2** — insert — `created_by_user_id` may be null, in which case activation segregation cannot fire — `routes/policy.py:56,91`
- **§3.4** — insert — promotion tests are non-null only, so `""` counts as a promotion — `routes/assessments.py:54`, `services.py:103,339`
- **§3.4** — insert — "every score field null" enumerated; `triggered_rule_codes` is null, not `[]`, until scoring — `routes/assessments.py:86-99`
- **§3.4** — insert — multiple whitelist exceptions resolve to earliest `created_at` — `services.py:206-227`
- **§3.4** — insert — `applied_exception_id` is set only when an `ADDRESS` rule's predicate actually held and was suppressed; otherwise null — `services.py:364-372`
- **§3.4** — insert — `good_customer_at_decision` snapshot read **before** this request's counter movements, so the flag-flipping approval records `false` — `services.py:433-436`
- **§3.4** — insert — review branch leaves `final_disposition`, `decided_at` and `good_customer_at_decision` null, the last permanently — `services.py:444-464`
- **§3.5** — insert — omitted `decision_note` leaves the existing value — `routes/risk.py:381,408-409`
- **§3.6** — insert — shift axis has no forbidden transitions; no-op re-assertion still bumps `version`; cascade only on `AVAILABLE →` non-`AVAILABLE` — `routes/entities.py:161-168`
- **§3.6** — insert — assignment preserves `escalated_by_analyst_id` and `escalation_count`; `priority_score` not recomputed — `services.py:564-571`
- **§3.6** — insert — omitted `resolution_note` leaves the existing note — `services.py:487-489,520-521`
- **§3.6** — insert — escalation **preserves** `assigned_at` — `services.py:549-551`
- **§3.7** — insert — recording an auth event has no customer-state gate; `prior_password_change_hours` accepts any number — `routes/risk.py:44-60`
- **§3.7** — insert — `ALLOWED`/`BLOCKED` leave both challenge fields null; step-up posture move fires only from `CLEAR`; containment skipped when already `CONTAINED`; skipped moves leave `version` alone — `routes/risk.py:66-105`
- **§3.7** — insert — `challenge_method` validated always but consumed only by `REISSUE` — `routes/risk.py:138-140,183`
- **§3.7** — insert — on `PASS` the posture move is conditional on `WATCH`; counter reset and `version` bump unconditional — `routes/risk.py:164-170`
- **§3.7** — insert — third-failure containment driven by attempt count alone, whatever the posture and without consulting `account_status` — `routes/risk.py:175-177`
- **§3.7** — insert — containment link 3 stamps `decided_at`, leaves `decision` at `REVIEW` and the snapshot null, and recomputes neither device nor cluster — `services.py:164-170`
- **§3.9** — insert — good cohort tests for exactly `true`, so null-snapshot (manually resolved) assessments are excluded — `services.py:726-727`
- **§4** — insert — `data` always holds the path-addressed resource, never a cascade target — `routes/assessments.py:250`, `routes/risk.py:191,284`

### Judgement calls worth flagging
- Two prose/impl orderings are *unobservable* and were left alone: `reshipper_confidence` caps before rounding (§2.10/§3.1 say cap after) — identical results because all contributions are exact hundredths; and the approve/review/decline branches recount *all* device and cluster signals rather than the subsets §3.4 enumerates — recounts are idempotent, so the extra fields never change value.
- `ERR_NOT_FOUND` and `ERR_METHOD_NOT_ALLOWED` were pinned in §2.2 prose rather than as new rows in the §5 catalogue table, to honour the "never add new sections" constraint.
