# Worklog — task_2406_executive_compensation_say_pay_disclosure

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2406_executive_compensation_say_pay_disclosure/` and `tasks/task_2406_executive_compensation_say_pay_disclosure/workspace/` (pre-allocated task name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-02T00:00:00.000Z

All three artifacts are complete and lint-clean.

**Files written** (`/home/ubuntu/github/CodingPRD/tasks/task_2406_executive_compensation_say_pay_disclosure/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys), scenario stored verbatim
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Scaffold size (well above the Expert band of 10–15 entities / 20–32 endpoints / 18–30 errors / 4+ state machines):**

| Table | Count |
|---|---|
| Entities (§1.1) | 12 (Company, PeerGroup, PeerGroupMember, Executive, PayProgram, IncentiveMetric, PayoutAward, CdaDraft, ProxyAdvisorScreen, OutreachEngagement, RestatementEvent, ClawbackDetermination) |
| State machines (§1.2) | 11 (incl. PayProgram's two parallel dimensions `design_status` / `vote_status`) |
| Concurrency rules (§1.2.1) | 3 OCC rules (peer group, pay program, incentive metric) |
| Calculations (§1.3) | 16, incl. 2 dual-variant (`benchmark_target_tdc` RAW_MEDIAN/SIZE_ADJUSTED, `realized_and_realizable_pay` REALIZED/REALIZABLE) |
| Validations (§1.4) | 47 priority-ordered rules |
| Endpoints (§1.5) | 54 (53 business + `POST /_clock/set_current_utc`) |
| Errors (§1.6) | 59 |
| Roles / SoD rules (§1.7) | 5 roles, 3 segregation-of-duties rules |

**Design files:** §1.8 = all 9 difficulty rules, 22 instances (≥2 each). §1.9 = 9 guide sections, 75 instances — 59 full test recipes + 16 `excluded_because:` stubs deferring to a named §1.8 instance.

**Verification performed:**
- `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (54 endpoints, 12 entities, 22 §1.8 instances, 59 §1.9 instances, 1037 calls scanned).
- All 97 instance names unique across the union of both design files; every stub's `difficulty_instance` citation resolves and no stub carries a `test_recipe`.
- All 59 error ids are triggered somewhere across the two design files.
- Custom placeholder-closure check: 0 unbound `${var}` references across all setup/trigger/assert lines in both files.
- Every numeric assert is a pre-computed literal (Decimal ROUND_HALF_UP), e.g. size-adjustment clamp fixture yields `benchmark_target_tdc_adjusted_usd == 10000000.00` vs. the unclamped 12,000,000.00; clawback fan-out yields determinations of 540,000.00 + 240,000.00 = 780,000.00; ISS 21.70 (LOW) vs Glass Lewis 32.85 (MEDIUM) on identical inputs.
- One SCAFFOLD.yaml fix applied during this pass: `CdaDraft.revision_round` default 1 → 0 to match the create side effect.

Note: the task directory already contained a pre-existing `worklog.md` and empty `workspace/` (timestamps predate this work); I left them untouched. Hard constraint respected — no sibling task directory was listed, globbed, grepped, or read.

## Step 3: Copy shared files — 2026-09-02T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T00:00:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2406_executive_compensation_say_pay_disclosure/workspace/PRD.md` — 457 lines, ends at §5 with no audit footer.

**Structure**

- §1 Introduction — 3 paragraphs (compensation-calendar framing, supersession theme, taxonomy of derivations / gates / cascades).
- §2 Global Specifications — 11 subsections: 2.1 RBAC (five roles, four `opaque` + one `entity_backed:Executive`), 2.2 API Response Structure (pasted verbatim, byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Common Resource Properties and the Logical Clock, 2.5 Monetary Precision/Ratios/Rounding Discipline, 2.6 Segregation of Duties, 2.7 Stale-Version Guards, 2.8 Cascade Propagation and Screen Freshness, 2.9 Path Resolution Order, 2.10 Validation Precedence (full 47-rung ladder), 2.11 Status Codes.
- §3 Business Logic — 9 subsections: issuer/peers/officers; peer-group construction, screening and approval; target-pay sizing; goal setting through certification; award granting, settlement and dual valuation; alignment and proxy-advisor screening; the disclosure cycle; outreach and the say-on-pay vote; restatements and clawback recovery.
- §4 — 54-row endpoint table (4 columns) with the 201/200 paragraph above it.
- §5 — 59-row error catalogue (2 columns).

**Coverage audit — all three Hard Contracts PASS**

```
Field coverage check:
- entities[].fields: 157 required, 157 present, 0 missing
- endpoints[].request_body: 77 required, 77 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 47 checked, 47 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 39 checked (11 machines), 39 fully expressed, 0 missing
- calculations[]: 16 checked, 16 fully expressed, 0 missing
- validations[] conditions: 47 checked, 47 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 36 checked, 36 expressed, 0 missing
- entities[].fields[] structured content: 157 checked, 157 reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked (4 payout-curve branches; VEST vs FORFEIT; RAW_MEDIAN vs SIZE_ADJUSTED; realized vs realizable; ISS vs GLASS_LEWIS; PASSED vs FAILED; the three interval conventions), 7 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 927
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All 59 error identifiers from `validations[]` and `concurrency_rules[]` appear backticked in the prose. The two withheld design files were not opened, and no sibling task directory was read.

Key judgement calls worth flagging: the scaffold's settlement transitions are triggered informally as `settlement: VEST`/`FORFEIT` while the endpoint input is `disposition`, so the prose uses `disposition`; and the deliberate asymmetry where member-add exempts both `BUSINESS_MODEL_ANALOG` and `TALENT_COMPETITOR` from the size band while the screen precondition exempts only `BUSINESS_MODEL_ANALOG` is stated explicitly rather than smoothed over.

## Step 5: Generate unit tests — 2026-09-02T00:00:00.000Z

Test generation is complete for `task_2406_executive_compensation_say_pay_disclosure`.

## Files written (9,516 lines)

**Stage 1 — `test_helpers/` (9 files, 3,256 lines)**
`__init__.py` (barrel), `types.py` (12 status enums + 19 value enums + 12 TypedDicts), `api_client.py` (55 endpoint methods + clock, prefix `/exec-comp`), `api_errors.py` (59 error ids + HTTP status map registered at import), `constants.py` (all pinned policy thresholds, company/executive/metric catalogues), `test_users.py` (5 roles, plus second-chair/second-counsel ids for the separation-of-duties rules), `factories.py` (one payload factory per write endpoint), `assertions.py` (entity + invariant assertions), `fixtures.py` (943 lines: atoms, list-based read-backs for the six entities with no single-resource GET, and 11 `setup_*` composites).

**Stage 2 — `test_suite/` (conftest + 17 test modules, 6,260 lines)**

## Test counts

| | tests | instances covered |
|---|---|---|
| Queue A (Difficulty) | 63 | 22 / 22, every one with ≥2 tests |
| Queue B (Corner) | 66 | 59 / 59 non-stub |
| **Total** | **129 functions → 135 collected cases** | **81 distinct Design tags** |

## Instances skipped

**None for coverage or derivability.** Every non-stub instance in both indices was translated. The only omissions are the **16 `excluded_because:` corner stubs** (5 state_machines, 5 calculations, 2 validations, 1 endpoints, 3 cross_cutting_layers) — no tests emitted, and I verified all 16 `difficulty_instance:` cross-references resolve to real rule_ids in the difficulty index.

Three localized softenings were used instead of skipping, each where the PRD requires a rejection but does not order the competing gates: repeat approval of an already-APPROVED peer group (`ERR_PEER_GROUP_NOT_SCREENED` vs `ERR_PEER_GROUP_NOT_MUTABLE`) via `validate_error_is_one_of`; and two assertions dropped rather than encoded (`market_data_updated_at is null`, forfeit `settlement_date`) because the PRD contradicts or leaves them open.

## Audit results — all clean

- 0 untagged, dual-tagged or dangling-tag tests; every `Design:` line is last in its docstring and resolves to a real instance name.
- Every docstring carries an ≥8-word substring that survives a literal match against `PRD.md`.
- 0 references to "scaffold" or any yaml section anywhere in `test_suite/`.
- No `pytest.skip`, `xfail`, `skipif`, TODO or placeholder anywhere.
- `py_compile` and `pyflakes` clean on all 27 files; `pytest --collect-only` gathers 135 tests.

## Design-index defects the agents found and corrected in the PRD's favour

Worth relaying to whoever owns the index or the implementation, since these tests will now surface the divergence:
- **Field-name mismatches:** index writes `say_on_pay_support_pct`/`achieved_factor_pct`/`adjustment_magnitude_pct`/`original_amount_usd`/`held_engagement_count`; the PRD names them `support_pct`, `payout_factor_pct`, `goal_adjustment_pct`, and does not declare the last two.
- **Enum values outside the declared domain:** outreach `channel` VIDEO_CALL/IN_PERSON/PHONE, and metric code `FCF_EPS` — substituted with valid values.
- **Self-inconsistent recipes:** several submit a CD&A for review while the program is still DRAFT (PRD rejects with `ERR_PROGRAM_NOT_MUTABLE`); one admits an out-of-band `TALENT_COMPETITOR` peer then expects screening to succeed; one pairs a restatement date before its lookback end.
- **Status-code conflict:** index puts `ERR_ISS_SCREEN_NOT_CURRENT` at 422; PRD §5 says 409.

## Step 6: Generate implementation — 2026-09-02T00:00:00.000Z

Implementation is complete and verified.

## Files written

All under `workspace/implementation/` — 23 files, ~3,460 lines:

- **Entry/infra**: `start.sh` (guards `pip install`, honors `$PORT`), `requirements.txt`, `app.py` (app factory, 10 blueprints, `ApiError`/`HTTPException` handlers, `threaded=False`, no reloader)
- **Core**: `db.py` (in-memory `Store` singleton + logical clock), `response.py` (envelope, `api_request_id`, `scrub()`), `errors.py` (59-entry catalogue), `middleware.py` (auth headers, RBAC), `validation.py`, `calc.py` (all pinned Decimal formulas)
- **Domain**: `services/domain.py` (cascade recomputation, `touch`/`apply_changes`, screen staleness → CD&A bounce-back)
- **Routes** (`routes/`): `common.py`, `companies.py`, `peer_groups.py`, `pay_programs.py`, `metrics.py`, `awards.py`, `cda.py`, `screens.py`, `outreach.py`, `restatements.py`, `clock.py`

## Endpoints

**54**, mechanically verified byte-identical to the PRD §4 table (normalized both the PRD table and Flask's `url_map` and diffed). Error catalogue also verified mechanically: 59/59 PRD error IDs present with matching HTTP statuses, plus one intentional extra (`ERR_NOT_FOUND` for unrouted paths).

## Notable design decisions

- **PRD §2.10's 47-step global precedence ladder overrides SCAFFOLD precondition order** wherever they conflict — e.g. SoD before metric state on `certify-result`, SoD before CDA state on `legal-clear`, program mutability before CDA state on `submit-review`, quiet period before window-in-past before overlap on `schedule`.
- **Engagement-hold cascade follows the PRD, not the SCAFFOLD**: SCAFFOLD said it recomputes `proxy_concern_score` for GLASS_LEWIS screens; PRD says every `SCREENED` screen goes `STALE`. Implemented the PRD behavior.
- **Version bookkeeping**: `touch()` is idempotent per request via `flask.g._touched_rows`, and `apply_changes(row, changes)` bumps `version` only when a value actually moves — so no-op writes don't inflate versions and multi-step cascades bump exactly once.
- **Storage is strictly in-memory** (`dict` keyed by UUID), zero seeding. Grep confirms no `open(`, `sqlite`, `json.dump`, `pickle`, or `/tmp` anywhere in the source.
- **Logical clock** cold-starts at a fixed `2026-08-01T00:00:00Z` (never wall clock), settable via `POST /_clock/set_current_utc`; `sec()` truncates to second granularity for every instant comparison.
- **`Decimal` + ROUND_HALF_UP throughout** with rounding order pinned per PRD (money/percent 2dp, ratios 4dp; the size-adjustment factor rounds to 4dp *before* multiplying; each metric contribution rounds individually before summing).
- **Uncatalogued guards map to `ERR_INVALID_REQUEST`/400** (refreshing a DELISTED company, empty market-data payload, `issuer_company_id` not flagged `is_issuer`, cross-issuer peer group or officer, wrong `units_granted` for the vehicle); excluding an already-EXCLUDED membership returns `ERR_PEER_GROUP_NOT_MUTABLE`/409.

## Verification

Three independent smoke suites, each run against a freshly relaunched server, all report `failures: 0`. Coverage includes the full happy path (register → peer group → screen → approve → program → metrics → approve → award → certify → vest → screens → CD&A → file → outreach → vote → restatement → analyze → order → acknowledge → recover → reverse), fresh-boot emptiness and pagination meta, auth/role/404 handling, the peer-group revert cascade, the L5 staleness bounce-back, same-investor overlap vs adjacency, coverage dedup by `investor_key`, the failing-vote branch and remediation, size-band and inclusion-reason asymmetries, RSU/PSU/FORFEIT valuations, the STEP curve with non-GAAP `achieved_value`, and conserving recover/reverse arithmetic. `__pycache__` was cleared so the delivered tree is source-only.

## Step 7: Run tests and iterate — 2026-09-02T12:05:00.000Z

RESUME NOTE (orchestrator): This task was resumed. Steps 1–6 artifacts were verified present and
valid on disk (SCAFFOLD trio non-empty; workspace/INSTRUCTION.md present; workspace/PRD.md complete
at 456 lines, ending in a full error-code appendix, not truncated; test_suite/ + test_helpers/
populated; implementation/ with start.sh present), so Steps 2–6 were NOT re-run. A prior Step 7
attempt had been interrupted: its 8 results files reported totals of 93–111 against a suite that
collects 135 cases, i.e. every round died before finishing — the classic un-setsid reaping
signature. It had also left un-validated edits to test_helpers/fixtures.py and
test_helpers/factories.py. All stale results.*.json and __pycache__ dirs were deleted and Step 7 was
re-run from a fresh baseline under setsid.

Clean sweep achieved. All 8 rounds: 135/135 passed.

## Summary

**Iterations run:** 2 (baseline sweep + one fix + confirming sweep).

**Baseline (iteration 1):** 7 of 8 rounds clean at 135/135; round 6 had one failure — `test_01_benchmark_variants.py::test_realized_and_realizable_totals_diverge_while_both_awards_stay_granted`, failing with `requests.exceptions.ConnectionError: ConnectionResetError(104, 'Connection reset by peer')` and no tripped assertion. The sweep ran correctly under `setsid` (server log contained only the runner's own `Killed`, never `Terminated`, and every round reported `total == 135`), so this was not a reaping artifact.

**Diagnosis (STEP 0 → STEP 2, test-infrastructure layer):** `test_helpers/api_client.py` creates one module-level `ApiClient()` singleton, and the runner's `GenericApiClient` base holds a single `requests.Session` — so one HTTP connection pool is shared by every test in a round. But `--isolation per-test-server` kills the server and reboots a new one on the *same* port before every test. A keep-alive socket pooled from the previous (now dead) server can outlive urllib3's `is_connection_dropped` liveness probe and get reused, and the request then dies mid-flight with exactly `ConnectionResetError(104)`. The race window is narrow, which matches the observed rate of 1 in 1080 test executions. This is a test-harness defect, not an implementation defect — the endpoint involved (`POST /exec-comp/companies/{id}/market-data`) has no timing logic, and the same test passed in the other 7 rounds.

**Tests deleted:** none. No failure was ever an assertion failure, so no PRD-coverage or unique-derivability question arose.

**Fixes applied to the test artifact (1 file):**
- `/home/ubuntu/github/CodingPRD/tasks/task_2406_executive_compensation_say_pay_disclosure/test_suite/conftest.py` — added an autouse `_fresh_connection_pool` fixture that calls `api_client.session.close()` before every test, clearing pooled sockets so each test connects to the server that is actually running. No assertion, payload, identity, or precondition was changed; nothing was skipped or weakened.

**Fixes applied to `implementation/`:** none. No PRD-required check was removed or relaxed, and no endpoint, field, or side effect was added.

**Fixes applied to `test_helpers/`:** none. The un-validated prior edits to `test_helpers/fixtures.py` and `test_helpers/factories.py` (timestamps 11:25/11:26) were re-derived against PRD.md and are consistent with it — notably the `investor_key` derivation (trim + upper-case, PRD §3.8), the version-guard threading through re-reads for all three §2.7 guards, the author/clearer split satisfying §2.6 segregation of duties, and the `CHAIR_TWO`-adjusts / `CHAIR_ONE`-certifies split. Both rounds of evidence confirm them: they were exercised by all 135 cases in all 8 rounds with zero assertion failures.

**Final sweep (per round passed/total):**

| Round | Passed/Total | Failed | Errors | Skipped | Duration |
|---|---|---|---|---|---|
| 1 | 135/135 | 0 | 0 | 0 | 324s |
| 2 | 135/135 | 0 | 0 | 0 | 325s |
| 3 | 135/135 | 0 | 0 | 0 | 319s |
| 4 | 135/135 | 0 | 0 | 0 | 315s |
| 5 | 135/135 | 0 | 0 | 0 | 320s |
| 6 | 135/135 | 0 | 0 | 0 | 321s |
| 7 | 135/135 | 0 | 0 | 0 | 319s |
| 8 | 135/135 | 0 | 0 | 0 | 319s |

Note on the count: the suite has 129 test functions, six of which are parametrized, so pytest collects 135 cases. Every round collected and ran all 135.

ORCHESTRATOR VERIFICATION: independently re-read all 8 results files — every round passed=135
total=135 failed=0 errors=0 skipped=0. Confirmed no `pytest.mark.skip` / `pytest.mark.xfail`
anywhere in test_suite/.

## Step 8: Finalize PRD — 2026-09-02T12:10:00.000Z

ORCHESTRATOR NOTE: Step 8's literal skip condition (0 iterations beyond baseline) was NOT met —
Step 7 ran 2 iterations and applied 1 test_suite/ fix — so Step 8 was run rather than skipped.
The single diff item was a pure HTTP-connection-pool fix, so a zero-edit outcome was the expected
and correct result. Verified with cmp + md5sum that PRD_FINALIZED.md is byte-identical to PRD.md.

## Result: zero edits — `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`

`workspace/PRD_FINALIZED.md` created via `cp`. Verified with `cmp` (exit 0) and `md5sum` (both `ce490ed8d791f1c007522a53748d4033`).

- **PRD.md:** 456 lines / 93,575 bytes
- **PRD_FINALIZED.md:** 456 lines / 93,575 bytes
- **%-delta:** 0.00% (0 lines added, 0 removed, 0 revised)

### Per-item verification of `<step_7_diff>`

**Item 1 — `test_suite/conftest.py`: new autouse `_fresh_connection_pool` fixture (the only fix in the diff).**
Read `test_suite/conftest.py` and `test_helpers/api_client.py`. The fixture body is exactly `api_client.session.close()` before each test. This is client-side HTTP connection-pool hygiene against the `--isolation per-test-server` reboot-on-same-port race. It touches no payload, no header identity, no precondition, no ordering, no error id, no formula, and no state transition. The rest of `conftest.py` is unchanged role-header fixtures plus the session-scoped `api` fixture. **No PRD-observable behavior → no PRD silence, no PRD mismatch, nothing to pin.**

**Confirming the failing test's rules are already uniquely pinned by PRD prose:** `test_01_benchmark_variants.py::test_realized_and_realizable_totals_diverge_while_both_awards_stay_granted`
- Endpoint `POST /exec-comp/companies/{id}/market-data`: pinned by PRD §3.1 line 183 (at-least-one-field / `ERR_INVALID_REQUEST`, overwrite semantics, `market_data_updated_at`, `version`, ACTIVE-only), line 185 (the four-part cascade, including "Fourth … a changed share price re-marks every award of the issuer's programs that is still `GRANTED`, rewriting each award's `realizable_value_usd` and then each affected program's `realizable_pay_total_usd`"), and the endpoint table line 341. Cross-read `implementation/routes/companies.py:80-133` — matches, and the handler contains no timing, ordering-by-clock, or nondeterministic logic, confirming the one-off `ConnectionResetError(104)` was transport-layer only.
- `realized_value_usd == 0.00` for `GRANTED` (and `FORFEITED`): PRD §3.5 line 261, quoted verbatim in the test docstring.
- Realizable formulas incl. the "certified if available, otherwise the assumed 100.00 percent" factor: PRD line 263; matches `implementation/calc.py:288-330` (`ASSUMED_TARGET_FACTOR_PCT`, `award_values`).
- Program totals, `pay_percentile_rank`, `degree_of_alignment`, `alignment_status`, `accepted_peer_count`, and the dedicated computed read: PRD line 271; matches `implementation/calc.py:336-360` and `implementation/services/domain.py:203-213`.

**Item 2 — tests deleted: none.** No assertion ever failed across both iterations (final sweep 8×135 clean), so no PRD-coverage or unique-derivability question arose. Nothing to pin.

**Item 3 — `implementation/` fixes: none.** No check removed or relaxed, no endpoint/field/side effect added. Nothing to pin.

**Item 4 — `test_helpers/` fixes: none.** The diff notes prior un-validated edits were re-derived and found PRD-consistent. Spot-checked the one with a concrete claim: `investor_key` = trim + upper-case is pinned verbatim by PRD §3.8 line 297, and `implementation/routes/outreach.py:45` does `investor_name.strip().upper()`; the same key drives overlap detection (`routes/outreach.py:97`) and coverage de-duplication (`calc.py:481`), both also pinned by PRD lines 301 and 303. No divergence, and no Step 7 fix here anyway.

### Per-edit pre-edit search log

Not applicable — no edits were made, so no (a)/(b)/(c) entries exist. Under the HARD SCOPE and NO-NEW-MISMATCH rules, manufacturing a PRD edit from a pure connection-pool fix would have created a fresh, unbacked claim for Step 9 to undo. I deliberately did not run a general PRD-vs-impl audit; one candidate ambiguity I noticed while confirming the above (PRD §3.5 line 251 reads as vacuously true for an award whose vehicle has zero metrics, while `implementation/calc.py:255-257` `certified_vehicle_factor` returns `None` on an empty metric set) is **not** traceable to any Step 7 fix and is therefore out of scope here — flagging it only so Step 9 can decide.

## Step 9: Complete PRD — 2026-09-02T12:22:00.000Z

## Result

- **Source vs output:** `PRD_FINALIZED.md` 456 lines / 93,575 chars → `PRD_COMPLETED.md` 456 lines / 97,520 chars (**+3,945 chars**, **0 line delta**, headings byte-identical — every change is an in-paragraph insert or revision; no new sections, no new paragraphs).
- **27 paragraphs touched, 33 distinct edits: 25 ambiguity-pins, 8 mismatch-revisions.**

### Carried-over Step-8 lead: confirmed and fixed
`calc.py:255-257` `certified_vehicle_factor` returns `None` on an empty metric set, and `routes/awards.py:84-86` calls it unguarded at grant time, so §3.5's "whenever **every** metric … is already certified" was indeed vacuously true for a zero-metric vehicle (and for every `RSU` award, since no metric can name that vehicle). Pinned at line 251.

### Changes
- §2.1 — insert — ambiguity — blank/whitespace-only `X-User-ID` also yields `ERR_UNAUTHENTICATED` — `middleware.py:39`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST` — `middleware.py:48-57`
- §2.3 — insert — ambiguity — created_at ties broken by insertion order — `db.py:132-134`
- §2.4 — revise — mismatch — cascade-reached rows bump `version`/`updated_at` only when a value actually moves; at most one bump per row per request — `db.py:110-129`
- §2.7 — insert — ambiguity — undeclared body fields ignored, not rejected — `validation.py:51-56`
- §2.8 — insert — ambiguity — group reverts only when a membership flips *from* in-band — `routes/companies.py:138-143`
- §2.10 step 4 — insert — ambiguity — wrong-typed FK → not-found; absent/null → step 6 — `routes/common.py:38-44`
- §2.10 step 6 — insert — ambiguity — free-text ceilings (500 / 2000 chars) — `routes/peer_groups.py:132`, `routes/metrics.py:108`
- §3.1 — insert — ambiguity — refreshing a `DELISTED` company is `ERR_INVALID_REQUEST` — `routes/companies.py:96-99`
- §3.1 — revise — mismatch — 4th cascade leg fires on `share_price_usd` being *supplied* (not changed) and re-derives the full alignment verdict, staling screens/sections — `routes/companies.py:101,151-161`
- §3.2 — insert — ambiguity — non-issuer `issuer_company_id` → `ERR_INVALID_REQUEST` — `routes/peer_groups.py:40-44`
- §3.2 — insert — ambiguity — already-`EXCLUDED` membership → `ERR_PEER_GROUP_NOT_MUTABLE`, group mutability tested first — `routes/peer_groups.py:135-140`
- §3.2 — insert — ambiguity — null benchmark at approval → `ERR_PEER_GROUP_NOT_SCREENED` — `routes/peer_groups.py:184-185`
- §3.3 — insert x3 — ambiguity — the three referential conditions are `ERR_INVALID_REQUEST`; `tsr_percentile_rank` defaults 0.00; vote tallies/`support_pct` null and `enhanced_engagement_required` false at creation — `routes/pay_programs.py:57-59,62-73,113-117`
- §3.3 — insert — ambiguity — `points` taken to two decimal places — `routes/pay_programs.py:176`
- §3.4 — insert — ambiguity — adjustment reason stored in `result_adjustment_reason` — `routes/metrics.py:131-136`
- §3.4 — insert — ambiguity — result submission omitting the reason preserves the existing one — `routes/metrics.py:151,163-164`
- §3.4 — revise — mismatch — certification level 4 stales screens on any §2.8-watched movement, not only `alignment_status` — `routes/metrics.py:196-198`
- §3.4 — revise — mismatch — level 2 fires on all-`CERTIFIED`-**or**-`RESTATED` — `calc.py:260`
- §3.5 — insert — ambiguity — omitted `units_granted` on `ANNUAL_INCENTIVE` = 0 — `routes/awards.py:43-44`
- §3.5 — revise — mismatch — empty metric set leaves the grant-time factor null (the Step-8 lead) — `calc.py:255-257`, `routes/awards.py:84-86`
- §3.5 — insert — ambiguity — forfeit ignores the supplied `settlement_date` — `routes/awards.py:176`
- §3.5 — revise — mismatch — both settlement branches stale screens on any watched movement — `routes/awards.py:168-184`
- §3.5 — insert — ambiguity — foreign `executive_id` filter → `ERR_NOT_RESOURCE_OWNER` — `routes/awards.py:112-114`
- §3.8 — revise — mismatch — `investor_key` is server-derived, client value ignored — `routes/outreach.py:45`
- §3.8 — insert — ambiguity — quiet period outranks the past-window check too — `routes/outreach.py:88-92`
- §3.8 — revise — mismatch — failed-vote bounce runs regardless of screens; non-CD&A `FILED` sections also clear `revision_round`/`cleared_by`/`filed_at` — `routes/pay_programs.py:313-325`
- §3.9 — insert — ambiguity — `restatement_date` before `lookback_end` → `ERR_INVALID_REQUEST` — `routes/restatements.py:45-46`
- §3.9 — insert x3 — ambiguity — `reversal_reason` mandatory; reversal sets `realizable_value_usd` equal to restored realized; reversal carries the same screen/section tail — `routes/restatements.py:318,338-351`

ORCHESTRATOR VERIFICATION: PRD_COMPLETED.md is 456 lines (same as source), 28 markdown headings
(same as source), heading text byte-identical to PRD_FINALIZED.md, and the diff touches 54 lines
(27 replaced paragraphs) — consistent with "27 paragraphs touched, no new sections". Step 9 edits
documentation only, so no re-sweep was required; the Step 7 clean sweep (8x 135/135) remains valid.

## PIPELINE COMPLETE — 2026-09-02T12:22:00.000Z

All artifacts present: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml,
workspace/INSTRUCTION.md, workspace/PRD.md, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md,
test_helpers/, test_suite/ (135 collected cases), workspace/implementation/ with start.sh, and
results.{1..8}.json all reporting 135/135.
