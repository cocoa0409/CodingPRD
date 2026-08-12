# Worklog — task_1263_charter_school_authorizing_renewal

## Step 1: Create task directory — 2026-08-12T11:36:22.000Z

Pre-assigned output folder `tasks/task_1263_charter_school_authorizing_renewal` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instructions; directory verified present and treated as done.

## Step 2: Generate scaffold — 2026-08-12T12:41:27.000Z

Done. All three scaffold artifacts were generated from the scenario description plus the skill spec only (no sibling tasks were read), written to `/home/ubuntu/github/CodingPRD/tasks/task_1263_charter_school_authorizing_renewal/`:

**Files (all exist, non-empty, valid YAML):**
- `SCAFFOLD.yaml` (95 KB) — §1.0–§1.7 only; no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (114 KB) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (182 KB) — single top-level key `scaffold_corner_design`

**Counts:**
- 15 entities (CharterApplication, CapacityInterview, School, CharterContract [self-referential renewal chain], PerformanceTarget, MonitoringReport, Lottery, LotteryEntry, InterventionNotice [escalation chain], CorrectiveActionPlan, RenewalDecision, ClosurePlan, StudentTransition, FeeInvoice, Appeal)
- 14 state-machine blocks (non-linear: CorrectiveActionPlan resubmit cycle, RenewalDecision DECIDED→REVERTED→DECIDED cycle, School parallel standing dimensions ×3, CharterApplication DENIED→BOARD_REVIEW appeal cycle)
- 2 OCC concurrency rules (`contract-create-stale-school` on School.version, `plan-create-stale-intervention` on InterventionNotice.version)
- 9 calculations (dual-variant application composite, reweighted compliance index, standing band thresholds, tiered renewal term eligibility, waterfall lottery assignment, seat-conservation invariant, base-first supplemental funding, per-month-rounded authorizer fee, fee-ledger conservation)
- 8 ordered validation priority rows; 49 error codes; 69 endpoints (incl. `POST /authorizer/_clock/set_current_utc` with pinned default `2026-05-01T00:00:00Z`); 7 roles with segregation-of-duties (scorer↔panelist, decider↔hearing officer, issuer↔resolver) and entity-backed SchoolOperator ownership
- Difficulty design: 20 instances across all 9 rules (rules 2 and 3 carry 3 each, covering modes a/b/c and cycle/parallel/appeal-cycle shapes)
- Corner design: 52 instances (48 active + 4 `excluded_because` stubs) across all 9 claim-guide sections

**Verification:** `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (1,098 calls scanned). A supplementary script confirmed zero dangling grounds refs, globally unique instance names, valid `excluded_because` targets, and full closure between validation/transition error references and the error catalog. All formula-derived asserts (composite 74.0/80.0, fees 6,528,000 / 8,127,996 cents, supplemental 3,820,800, indices 56.7/65.0, term tier 10) were precomputed by hand against the pinned formulas.

## Step 3: Copy shared files — 2026-08-12T12:41:51.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1263_charter_school_authorizing_renewal/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-12T13:04:47.000Z

PRD generated and verified. File: `/home/ubuntu/github/CodingPRD/tasks/task_1263_charter_school_authorizing_renewal/workspace/PRD.md` (365 lines, 57,356 bytes; ends at §5 with no audit footer).

**Section list**
- §1 Introduction (3 paragraphs: oversight duty → pain points → system scope, `/authorizer` mount)
- §2 Global Specifications (9 subsections): 2.1 RBAC + per-role identity prose (SchoolOperator entity-backed; six opaque roles named individually), 2.2 Response Structure (byte-verbatim from `section-2.2-response-structure.md`, confirmed programmatically), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields, list filters), 2.4 Resource Identity/Timestamps/Versioning, 2.5 Logical Clock (startup default 2026-05-01T00:00:00Z, half-open vs closed interval semantics), 2.6 Precision/Rounding/Money, 2.7 OCC (both write endpoints named literally, exact error IDs + 412), 2.8 Segregation of Duties (all four SOD rules), 2.9 Validation Layer Ordering + uniqueness catalog
- §3 Business Logic (9 subsections): application pipeline (intake/rubric/interview/decide), contracts + performance targets, monitoring + standing bands + auto-notice cascade, lottery + preference verification + seat conservation, interventions + corrective plans, renewal (window, eligibility tiers, decide, finalize forks), closure + student transitions, fee invoices (funding bands, fee tiers, pinned per-month rounding, ledger invariant), appeals + all four overturn cascades
- §4 Endpoint table: 69 rows, 4 columns only (Method, Path, Description, Authorized Roles)
- §5 Error catalogue: all 49 error IDs, 2 columns only

**Hard contract reports**
- Field coverage: entities[].fields 101 required (incl. endpoint inputs, query params, path params, common fields, `review_scores` entry keys), 101 present, 0 missing — PASS
- Rule coverage: validation priority chain expressed with explicit ordering (§2.9); 2/2 OCC rules expressed (endpoint + `expected_*_version` + exact error ID + 412, stale-read framing); all 60+ state transitions expressed with preconditions/side effects; all 9 calculations in precise reconstructible prose (constants embedded with cent-to-dollar conversions, no pseudocode, no fuzzy words); all 49 error IDs matchable to trigger conditions in §2/§3; sibling branches symmetric (decide/review/certify/rule pairs, 4 appeal cascades, 4 standing bands, 3 funding bands, 3 fee tiers, 4 renewal tiers) — PASS
- Path purity: 693 backtick tokens scanned in §3, 0 paths, 0 bare HTTP methods, 0 method+path combos — PASS

**Coverage notes:** all role names, enum/state values, and endpoint method+path pairs verified present programmatically; no operator-syntax or fuzzy-word leaks; §2.2 confirmed byte-identical to the canonical source. The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, and no sibling task directories were read.

## Step 5: Generate unit tests — 2026-08-12T13:46:07.000Z

Test generation for task_1263 is complete. Summary:

## Output

**`test_helpers/` (9 files, ~2,300 lines)**
- `types.py` — 15 entity TypedDicts (all carry id/created_at/updated_at/version), 24 status/enum classes, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with 68 endpoint methods covering every PRD §4 endpoint; module-level `api_client`
- `api_errors.py` — `ApiErrorId` (49 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserts plus domain invariants `assert_invoice_ledger_invariant` and `assert_lottery_seat_partition`
- `factories.py` — 15 payload factories (input fields only)
- `constants.py` — thresholds from PRD §3 calculations + logical-clock landmarks
- `test_users.py` — `TEST_USERS` for all 7 roles + per-instance `make_*_headers` builders (mandatory `make_school_operator_headers(school_id)` for the entity-backed role)
- `fixtures.py` — composite tiers: application progression (`create_application[_under_review]`, `post_full_rubric`, `create_scored_application`, `create_board_ready_application`, `create_approved_school`, `create_denied_application`), `create_open_school` (standard fixture: approval → draft contract → 3 targets → activate), monitoring reports, lotteries, interventions/plans, `setup_renewal_ready_school` (3-report track record avg 90.3 + clock in renewal window), fees, closures, appeals

**`test_suite/` (17 test files + conftest.py, 86 tests)** — organized by concern: composite scoring, fee billing, renewal decisions, interventions/plans, cascades, validation priority, lottery, intervals/OCC, entity basics, application guards, monitoring, lottery guards, intervention guards, closure, renewal windows, appeals, envelope/computed.

## Coverage
- **Queue A (Difficulty): 20/20 instances, 40 tests (exactly 2 each)** — all translated, including both priority-pair conflict tests (PRD §2.9 layer ordering covers them), both OCC tests, both temporal-overlap geometries, and the depth-3 renewal-denial cascade.
- **Queue B (Corner): 46 of 48 non-stub instances covered (1 test each)**; 4 `excluded_because` stubs not translated (cross-references verified to resolve).

## Skipped instances (PRD-first filter)
1. **`Corner/errors/error_score_out_of_range`** — asserts rubric score 101 → ERR_INVALID_REQUEST, but the PRD's 0–100 range applies only to `panel_score` (§3.1) and monitoring scores (§3.3); no verbatim rubric-score range exists. Not uniquely derivable.
2. **`Corner/consistency_model/consistency_immediate_read_after_write`** — asserts `rubric_score == 70.0` after one criterion; PRD §3.1 contradicts this ("The `rubric_score` — null until the rubric is complete"). Asserted outcome not PRD-derived.

One assertion-level narrowing: `entity_application_creation_defaults` was generated but drops `composite_variant == 'PROVISIONAL'` at creation — PRD §3.1 pins the variant only "from the moment the rubric completes"; all other asserted defaults are verbatim-PRD.

## Self-check verdicts
- Compile: all 26 files pass `py_compile`; `test_helpers` imports cleanly (73 client methods, 49 error ids)
- Collection: `pytest --collect-only` → 86 tests, no errors
- Tag audit: 86/86 tests carry exactly one `Design:` line; all tags resolve to real instances; difficulty ≥2/instance, corner live ≥1/instance; stubs have 0 tests; no skip/xfail markers; no "scaffold" references in generated code
- PRD citation audit: every quoted span ≥30 chars in every docstring survives whitespace-normalized verbatim match against PRD.md

Gaps stay gaps per the spec — the two skipped corner instances are PRD-side defects, not test-suite weakening.

## Step 6: Generate implementation — 2026-08-12T13:46:07.000Z

## Summary

Complete Python + Flask implementation for `task_1263_charter_school_authorizing_renewal` is on disk at `/home/ubuntu/github/CodingPRD/tasks/task_1263_charter_school_authorizing_renewal/workspace/implementation/`.

### File inventory
- `start.sh` (executable, `-rwxrwxr-x`) — guarded dep install (`if ! python3 -c "import flask"`), then `exec python3 app.py` in foreground
- `requirements.txt` — Flask only
- `app.py` — entry point, blueprint registration, error handlers (ApiError → envelope; 404/405 → `ERR_NOT_FOUND`; catch-all → 400 envelope); binds `0.0.0.0:$PORT` (default 10000)
- `clock.py` — logical clock, startup default exactly `2026-05-01T00:00:00Z`, never wall-clock; ISO 8601 UTC with 3 fractional digits
- `db.py` — in-memory dict-per-entity store, starts empty, `id`/`created_at`/`updated_at`/`version` server-managed per PRD §2.4
- `errors.py` — all 49 error IDs from scaffold §1.6 with exact HTTP statuses
- `response.py` — success/error envelopes per PRD §2.2 (`meta.api_request_id` `req_…`, `api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta)
- `middleware.py` — layer-1 header auth (`X-User-ID`/`X-User-Role`, 7 roles), layer-2 role check, layer-3.5 SchoolOperator ownership, typed field validators
- `routes/` — `clock_routes.py`, `applications.py` (incl. interviews blueprint), `schools.py`, `contracts.py`, `monitoring.py`, `lotteries.py`, `interventions.py` (incl. corrective plans), `renewals.py`, `closures.py` (incl. student transitions), `fees.py`, `appeals.py`, plus `common.py` (existence + pagination + filters)
- `services/` — `calc.py` (rubric/composite weighted scoring, compliance index with failing-domain weight doubling, standing bands, fee/funding pinned order with per-month rounding — all `Decimal` ROUND_HALF_UP), `cascade.py` (approve→school create, monitoring-accept standing cascade + auto-PROBATION notices, lottery cancel cascade, school closing/closed cascades, standing one-step upgrade, renewal eligibility tiers)

### Route table vs scaffold
69 endpoints in SCAFFOLD.yaml; 69 (method, path) pairs registered in Flask; **0 missing, 0 extra** (verified programmatically with YAML-parsed scaffold vs `app.url_map`).

### Boot check
- `bash start.sh` on scratch ports 18123 and 18234 boots cleanly in ~2 s
- Unauthenticated `GET /authorizer/applications` → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` with correct error envelope
- Authenticated list → 200 with `limit:10, offset:0, total_count:0, has_more:false`
- `POST /authorizer/_clock/set_current_utc` advances the clock; default reads `2026-05-01T00:00:00.000Z`
- Server killed after verification; no residual listener

### Behavioral spot-checks passed (live server)
- Full application pipeline: intake → rubric scores (PROVISIONAL composite = rubric mean) → interview scheduling with SOD reviewer/panel conflict and `ERR_NOT_PANELIST` → panel scoring flips composite to FINAL (`0.6·rubric + 0.4·interview`, e.g. 80/70 → 76.0) → board approve → School PRE_OPENING with all standings GOOD
- Contract OCC: `ERR_STALE_SCHOOL_VERSION` (412) on stale version; targets + weight-sum activation guard; activation supersedes and opens school
- Monitoring: compliance index with failing-domain reweighting (85/70/45 → 66.0), accept cascade set bands and auto-created an ISSUED PROBATION notice for the CRITICAL domain; plan create OCC + ownership + SOD self-resolve; resolve upgraded CRITICAL→PROBATION exactly one step
- Lottery: PENDING entries block seal, preference verification, execute ranking (VERIFIED-with-codes weight 10 first), decline promotes smallest-rank WAITLISTED
- Fees: pinned order — band keyed on base alone (125,000,000 → SMALL 0.12), supplemental 2,400,000, per-month rounding `round(127,400,000 × 0.025 / 12) = 265,417` → billed 3,185,004; finalize recomputes under FINAL variant; pay settles in full
- Appeals: APPLICATION_DENIAL filed by Applicant with `school_id` null; hearing officer SOD conflict vs original decider; ruling officer mismatch; OVERTURNED returned application DENIED→BOARD_REVIEW with denial fields cleared
- Renewal: window `ERR_RENEWAL_WINDOW_NOT_OPEN` outside [term_end−365d, term_end−30d]; eligibility snapshot 0 with no ACCEPTED reports; `ERR_RENEWAL_NOT_ELIGIBLE` on RENEWED; finalize blocked while clock ≤ decided_at+30d; after window, DENIED finalize drove school OPEN→CLOSING, created NON_RENEWAL ClosurePlan (`decided_by_user_id: "system"`), and stepwise advance to CLOSED revoked the ACTIVE contract and closed the school

No seeding, no persistence — the store is pure in-memory dicts, empty at every boot.

## Step 7: 8-round stability sweep loop — 2026-08-12T14:05:00.000Z

Sweep 1 (baseline): 76/86 in all 8 rounds; union of 12 failing test-instances.
Sweep 2 (after fixes): **86/86 in all 8 rounds, 0 failed, 0 errors** (~115 s/round).

Diagnoses and fixes (no tests deleted; every asserted rule traced to verbatim PRD prose):

1. **Implementation bug — `services/calc.py::compute_composite`**: scoring an interview before the rubric completes (allowed by PRD §3.1 — scheduling/scoring require only `UNDER_REVIEW`) crashed on `Decimal(str(None))` and surfaced via the catch-all as 400 `ERR_INVALID_REQUEST`. Fixed so a null `rubric_score` yields null `composite_score` (variant `FINAL` once an interview score exists, `None` otherwise); the FINAL composite is computed when the rubric later completes.
2. **Test bug — `test_suite/test_04_interventions_and_plans.py`**: class method `_standing_context(self)` was invoked as a bare name (`NameError`) in both `TestSchoolParallelStandingIndependence` tests; changed to `self._standing_context()`.
3. **Test bug — `test_suite/test_05_cascades.py`**: `_cascade_context` used the pytest-fixture name `api` outside test scope (`NameError`); changed to the module-level `api_client`.
4. **Test bug — `test_suite/test_07_lottery.py`**: module-level `_executed_lottery_context` used `api` (`NameError`); changed to `api_client` (3 sites).
5. **Test assertions relaxed to PRD-pinned semantics — timestamp instants**: four assertions compared clock-derived fields (`corrective_due_date` ×2 in test_05/test_13, `decided_at` and successor `term_start` in test_15) against exact strings without fractional digits, while PRD §2.4 pins three fractional digits only for `created_at`/`updated_at` and §2.2 for envelope timestamps. Added `assert_same_instant`/`parse_instant` to `test_helpers/assertions.py` and compare parsed instants — the PRD-covered rule (clock + 30 days; decided_at = the clock; term_start = day after prior term_end) is still asserted exactly.

Sweep-1 `ERROR`s ("API server could not be restarted", 4 test-instances across rounds) were runner-level boot-poll timeouts under 8× lockstep load; they did not recur in sweep 2 (688/688 clean restarts), with no change made to `start.sh`.

Verbatim subagent summary:

## Summary

**Iterations run:** 2 sweeps (16 total rounds). Sweep 1: 76/86 in every round (12 failing test-instances in the union). Sweep 2 after fixes: **86/86 passed, 0 failed, 0 errors in all 8 parallel rounds** (~115 s/round, 688/688 clean server restarts).

**Tests deleted:** none. Every failing assertion traced to verbatim PRD prose, so no PRD-silence deletions were warranted.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1263_charter_school_authorizing_renewal/test_helpers/assertions.py` — added `parse_instant`/`assert_same_instant`. Rationale: PRD §3.5/§3.6 pin the *instant* (`corrective_due_date` = clock + 30 days; `decided_at` = the clock; successor `term_start` = day after prior `term_end`), but §2.4 pins the three-fractional-digit serialization only for `created_at`/`updated_at`. The 4 exact-string assertions (test_05:122, test_13:149, test_15:36, test_15:54) were not uniquely derivable on format; per STEP 1c the covered instant assertion was kept, the unpinned serialization assertion removed.

**Fixes applied to `test_suite/`:**
- `test_04_interventions_and_plans.py` — `_standing_context(self)` → `self._standing_context()` (2 sites); the helper is a classmethod-style method, bare-name calls raised `NameError`.
- `test_05_cascades.py` — `_cascade_context` used the pytest-fixture name `api` outside test scope → `api_client.accept_monitoring_report(...)`.
- `test_07_lottery.py` — module-level `_executed_lottery_context` used `api` → `api_client` (3 sites).

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1263_charter_school_authorizing_renewal/workspace/implementation/services/calc.py` — `compute_composite`: handle `rubric_score is None` when an interview is scored before the rubric completes (PRD §3.1 gates scheduling/scoring only on `UNDER_REVIEW`, so this path is legal). Previously `Decimal(str(None))` crashed and the catch-all returned 400 `ERR_INVALID_REQUEST` ("decimal.ConversionSyntax"). Now: null rubric → null composite (variant `FINAL` if an interview score exists, else `None`); the FINAL composite is computed once the rubric completes. All PRD-specified paths (PROVISIONAL = rubric mean; FINAL = 0.6·rubric + 0.4·interview) are unchanged.

**Infra note:** sweep 1 showed 4 runner-level "could not be restarted" setup ERRORs (15 s boot-poll timeouts under 8× lockstep load). They did not recur anywhere in sweep 2; no change to `start.sh` was needed.

## Step 8: Finalize PRD — 2026-08-12T14:09:53.000Z

PRD_FINALIZED.md is written to disk with exactly one targeted edit. Final summary:

## Summary

**Line counts:** PRD.md = 365 lines; PRD_FINALIZED.md = 365 lines; 0% line-count delta (one in-place paragraph revision, no lines added or removed).

**Changes (one total):**
- §3.1 (paragraph on capacity-interview scoring, line 137) — **revise** — Split the interview-scoring ripple into two cases: `interview_score` and the `composite_variant` flip to `FINAL` always happen at scoring, but `composite_score` is recomputed as 0.6·rubric + 0.4·interview only when the rubric is already complete; if the interview is scored before the rubric completes (legal, since scheduling/scoring gate only on `UNDER_REVIEW`), `composite_score` remains null with variant `FINAL`, and the FINAL composite is computed when the rubric later completes — `implementation/services/calc.py:48-59` (`compute_composite` null-rubric branch added in Step 7), exercised via `implementation/routes/applications.py:242-262` (`score_interview`) and `implementation/services/cascade.py:14-22` (`recompute_application_scores`).

**Step 7 diff items not resulting in PRD edits:**
- `test_helpers/assertions.py` (`parse_instant`/`assert_same_instant`) — Step 7's own rationale says the serialization format of `corrective_due_date`/`decided_at`/successor `term_start` was *not uniquely derivable* from the PRD and the format assertions were removed; the PRD stays silent on it by design. No impl behavioral choice needed pinning beyond what §2.4/§3 already state (the impl happens to serialize via 3-fractional-digit ISO in `implementation/clock.py:51-59`, but pinning that in the PRD would contradict Step 7's deliberate weakening).
- `test_04`, `test_05`, `test_07` fixes — pure fixture bugs (`_standing_context(self)` → `self._standing_context()`, `api` → `api_client`); explicitly not PRD silence.

**Per-edit pre-edit search log:**

*Edit 1 (§3.1 line 137 — composite ripple on interview scoring):*
- (a) **Subject:** application `composite_score`/`composite_variant` behavior when an interview is scored while `rubric_score` is still null.
- (b) **Impl paths enumerated and read:** `implementation/services/calc.py` (full file; `compute_composite` at lines 48-59); `implementation/services/cascade.py:14-22` (`recompute_application_scores` — sole writer of the composite fields); `implementation/routes/applications.py` (full file — creation init at 35-51, `post_score` → recompute at 85-107, `advance_to_board` gate at 180-191, `decide_application` null-safe threshold check at 194-232, `score_interview` → recompute at 242-262); grepped `implementation/routes/appeals.py` for `composite|interview_score|rubric` (no hits — overturn cascade does not touch these fields); grepped all `compute_composite`/`recompute_application_scores` callsites repo-wide (exactly two callsites, both enumerated).
- (c) **Wording adjustment:** The initial draft said "if the rubric is already complete" without justifying the ordering's legality; I added the clause "Because interview scheduling and scoring are gated only on `UNDER_REVIEW`" to anchor the new branch to gating language already present in §3.1 (line 135), and kept the FINAL formula wording byte-identical to the original sentence so the rubric-complete path is described exactly as before. Verified the revised sentence stays consistent with all enumerated paths: creation (composite null — unchanged, §3.1 line 133 already implies non-PROVISIONAL before rubric completion), PROVISIONAL path (line 133 kept verbatim — vacuously true under interview-first ordering), advance-to-board freeze (line 139 — unaffected, composite always FINAL-computed by then), and decide threshold (line 141 — unaffected).

## Step 9: Complete PRD — 2026-08-12T14:19:46.000Z

PRD_COMPLETED.md is written and verified on disk at `/home/ubuntu/github/CodingPRD/tasks/task_1263_charter_school_authorizing_renewal/workspace/PRD_COMPLETED.md`.

## Summary

- **Source vs. output:** PRD_FINALIZED.md = 365 lines / 57,778 chars; PRD_COMPLETED.md = 365 lines / 59,934 chars (char-delta +2,156; all edits are in-paragraph, no lines or sections added).
- **Counts:** 18 ambiguity-pins, 1 mismatch-revision (19 changed paragraphs, 20 diff lines).

Changes (all edits target PRD_COMPLETED.md only):

- §2.3 — revise — ambiguity — pinned pagination tie-break (`id` ascending) and `ERR_INVALID_REQUEST` for non-integer/out-of-range `limit` or negative `offset` — routes/common.py:23-46
- §2.5 — revise — ambiguity — unparseable `to_iso8601` rejected with `ERR_INVALID_REQUEST` — routes/clock_routes.py:18-21
- §2.9 — insert — ambiguity — `ERR_INVALID_REQUEST` field validation has no layer of its own; each endpoint validates a field at the point of consumption — middleware.py:66-102 and per-endpoint inline ordering (e.g. routes/interventions.py:140-146, routes/closures.py:27-33)
- §3.1 — revise — ambiguity — new application initializes `rubric_complete` false and `rubric_score`/`interview_score`/`composite_score`/`composite_variant` all null — routes/applications.py:35-49
- §3.1 — revise — ambiguity — unknown `criterion` → `ERR_INVALID_REQUEST`; rubric `score` accepted as any number with no range check — routes/applications.py:93-96
- §3.1 — revise — ambiguity — `panelist_user_ids` must be a non-empty array of strings, else `ERR_INVALID_REQUEST` — routes/applications.py:119-121
- §3.2 — revise — ambiguity — non-null `prior_contract_id` must name an existing contract, else `ERR_NOT_FOUND` — routes/contracts.py:29-33
- §3.3 — revise — ambiguity — domain score outside 0–100 → `ERR_INVALID_REQUEST` — routes/monitoring.py:22-24,38-40
- §3.4 — revise — ambiguity — omitted `preference_codes` treated as empty list; unknown code → `ERR_INVALID_REQUEST` — routes/lotteries.py:87-96
- §3.4 — revise — ambiguity — lottery-open guard order pinned: lottery's own state checked before school-OPEN — routes/lotteries.py:66-71
- §3.5 — revise — ambiguity — resolving a `COMPLIANCE`-domain notice lifts no standing (school has none) — services/cascade.py:129-140
- §3.5 — revise — ambiguity — escalation successor copies the original notice's `reason` — routes/interventions.py:93-103
- §3.5 — revise — ambiguity — plan resubmission clears `review_notes` as well as `reviewed_by_user_id` — routes/interventions.py:216-220
- §3.6 — revise — ambiguity — `contract_id` naming an existing contract of a different school → `ERR_NOT_FOUND` — routes/renewals.py:27-28
- §3.6 — revise — ambiguity — finalize: successor `term_end` keeps month/day with Feb 29 → Feb 28 fallback; DENIED cascade plan carries `closure_date` null — routes/renewals.py:128-132,150-156
- §3.7 — revise — ambiguity — invalid `reason` or missing/empty `closure_date` on manual closure → `ERR_INVALID_REQUEST` — routes/closures.py:27-31
- §3.8 — revise — ambiguity — negative `estimated_enrollment`/`base_per_pupil_cents`/`qualifying_supplemental_pupils` (and negative `audited_enrollment` at finalize) → `ERR_INVALID_REQUEST` — routes/fees.py:32-33,77-78
- §3.9 — revise — mismatch — appeal window's "decision instant" pinned: `decided_at` for renewal decisions, but the target's `updated_at` for applications, contracts, and invoices — routes/appeals.py:36,41,46,51
- §3.9 — insert — ambiguity — role/type exclusivity at filing (`Applicant` only for `APPLICATION_DENIAL`, `SchoolOperator` for the rest, else `ERR_INSUFFICIENT_PERMISSIONS`); `school_id` required and must exist (`ERR_NOT_FOUND`) for school-scoped appeals — routes/appeals.py:66-77

Deliberately left unpinned as PRD-consistent: enum-value rejections all map to the catalogue's sole generic 400 (`ERR_INVALID_REQUEST`), and the escalation path's two `version` bumps remain compatible with §2.4's per-mutation wording.
