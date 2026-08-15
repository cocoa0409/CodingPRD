# Worklog — task_1924_legal_aid_intake_case_assignment

Scenario: 1924. Legal Aid Intake & Case Assignment (legal aid society). Difficulty directive: harder than expert level.

## Step 1: Create Task Directory — 2026-08-15T01:06:00.000Z

Pre-completed by the invoking pipeline: `tasks/task_1924_legal_aid_intake_case_assignment/` and its `workspace/` already existed; no directory scanning or index computation performed (per invocation args).

## Step 2: Generate Scaffold — 2026-08-15T01:58:30.000Z

All three artifacts are complete and lint-clean. Summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1924_legal_aid_intake_case_assignment/SCAFFOLD.yaml` (1147 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_1924_legal_aid_intake_case_assignment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (680 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_1924_legal_aid_intake_case_assignment/SCAFFOLD_CORNER_DESIGN.yaml` (1537 lines)

## Counts

| Metric | Count |
|---|---|
| Entities | 14 |
| State machines | 6 |
| Calculations | 8 |
| Validation rows (ordered priorities) | 36 |
| Endpoints | 67 |
| Error codes | 42 |
| Roles | 7 |
| §1.8 difficulty instances | 20 (every rule ≥ 2) |
| §1.9 corner instances | 72 (67 active + 5 `excluded_because` stubs) |
| Lint | `VERDICT: clean lint` — 960 test-recipe calls scanned, 0 violations; all 15 FKs reverse-reachable |

## Complexity profile

Primary archetype **quota/allocation** (caseload units + grant budget cents) with secondary **compliance/audit**; layers: selector_policy, rate_threshold_triggers, dual_variant_calculation, optimistic_concurrency. Flat topology with a self-referential `StaffMember.supervising_attorney_id`; segregation-of-duties role model.

## Notable design decisions

- **Dual-variant pairs across domains**: income screening (standard gross-income cap 125.00 with benefits auto-pass vs grant countable-income cap, both stored per screen) and caseload (raw count vs weighted 5/2 units).
- **Combinatorial formulas in all three modes**: (a) priority score with capped vulnerability multiplier + tiered urgency + 100 cap; (b) grant drawdown pinned to round-per-case-then-sum (39,999 vs 40,000 divergence); (c) service-level gate with pinned pre-opening pool evaluation to break the capacity↔weight circularity.
- **Parallel state axes on Case** (status × funding_status) with a falsifiable independence probe: grant resume restores funding but leaves the case ON_HOLD.
- **Depth-3 transitive cascade**: grant suspend → case funding frozen → forced ON_HOLD → attorney load released; depth-2 cascade from `PATCH /clients` → WAITLISTED app reverts → waitlist entry deleted.
- **Two OCC true-race rules** (case assign supersede, application rescreen) on `version`, both serially reproducible; state checks pinned *before* OCC in validation order.
- **Contrasting interval semantics for Rule 8**: half-open referral service windows (adjacency allowed) on ReferralPanelMember vs closed grant periods (boundary touch = overlap) scoped per funder.
- **Pinned 4-step daily sweep** (conflict expiry → referral expiry → advice auto-close → waterfall promotion) whose ordering is observable: same-sweep auto-close frees pool units consumed by promotion; waterfall skips oversized head entries (no head-of-line blocking), ranked by priority DESC / created_at ASC (never id).
- **SoD edges**: conflict checker ≠ ethics resolver (`ERR_ETHICS_RECUSAL`), screener ≠ case opener (`ERR_SELF_SCREENING_APPROVAL`); ownership-scoped time-entry/closure for StaffAttorney/Paralegal.
- Logical clock endpoint with the mandated startup default `2026-08-01T00:00:00Z`, driving 45-day conflict validity, 10-day referral offers, and 30-day advice windows.
- All numeric asserts were pre-computed from the formulas (e.g., 125.00 exact-boundary income 1,882,500¢; priority 85.00 = 50×1.30+20; report hours 3.75 = 1.50+2.25).

## Step 3: Copy Shared Files — 2026-08-15T02:00:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1924_legal_aid_intake_case_assignment/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T02:20:00.000Z

The PRD is complete and all three hard contracts pass. Final report:

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1924_legal_aid_intake_case_assignment/workspace/PRD.md` — **360 lines**. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

### Section list

- **§1. Introduction** — 2 paragraphs (double-scarcity business context: weighted caseload units + grant cents, plus ethics SoD)
- **§2. Global Specifications** — 2.1 User/RBAC (7 roles, per-role `identity:` prose), 2.2 API Response Structure (**verified byte-identical** to `section-2.2-response-structure.md`), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, waitlist exception), 2.4 The Logical Clock (default 2026-08-01T00:00:00Z, strict deadline comparisons), 2.5 Common Resource Properties (9 common-fields entities vs 5 `id`+`created_at`-only entities), 2.6 Nested Path Resolution, 2.7 Validation Order & Error Precedence (13-step cascade, first-failure-wins), 2.8 OCC, 2.9 Precision/Rounding, 2.10 Caseload Weight Units, 2.11 Grant Ledger Conservation
- **§3. Business Logic** (9 subsections, process-timeline grouping): 3.1 Client Registration & Household Finances, 3.2 Application→Eligibility (intake/docs-loop/screen/decide/rescreen/withdraw), 3.3 Conflict Clearance & Ethics, 3.4 Waitlist & Unmet Need, 3.5 Open-Case Gauntlet & Grant Reservation (pinned 7-step order), 3.6 Assignment & Caseload, 3.7 Pro Bono Referrals & Panel, 3.8 Timekeeping/Closure/Surveys, 3.9 Operations Admin (venue rules, grants + 3-link suspend cascade, reports, pinned 4-step sweep)
- **§4. Endpoint Definitions** — 67/67 scaffold endpoints, 4-column table only
- **§5. Error Code Catalogue** — 42/42 errors, 2-column table only

### Coverage audit

- **Contract 1 (Field-Name Coverage):** 244 required identifiers (all `entities[].fields`, all endpoint `input`/`output`/path params, envelope/pagination names, error ids, role names, state/enum values) — **0 missing** after mechanical diff against the scaffold. (First audit pass produced a false failure: fenced JSON blocks in §2.2 phase-shifted naive backtick pairing; the checker was fixed to strip fences, then passed.)
- **Contract 2 (Rule Coverage):** 34/34 validation entries expressed with priority ordering (global cascade §2.7; pinned open-case gauntlet §3.5; pinned sweep order §3.9); 2/2 OCC rules (assign → `expected_case_version`, rescreen → `expected_application_version`, both `ERR_STALE_VERSION`/412, stale-observation framing, no race language); 44/44 state transitions (incl. all 6 withdraw branches with the INELIGIBLE no-record asymmetry, both funding-axis freeze/resume cascades); 8/8 calculations in reconstructible prose (FPL 1,506,000 + 538,000/member, ≤125.00 inclusive auto-pass, priority multiplier 0.15-step/1.75-cap/urgency 20-10/100.00 cap, 5-vs-2 weights with the 4-vs-11 raw/weighted example, pinned per-case cent rounding with the 33,333-cent→39,999 example, waterfall with no head-of-line blocking, report aggregation, sweep strict-before comparisons); all multi-endpoint `applies_to` scopes enumerated (panel ACTIVE at offer **and** accept, capacity at assign **and** resume, ownership at close **and** time-entry). **Gap found and fixed:** `assigned_attorney_id` null while `PRO_BONO`-placed was only implicit — added an explicit clause to the §3.7 acceptance paragraph.
- **Contract 3 (§3 Path Purity):** 603 backtick tokens in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos.
- Auxiliary checks: all 42 error ids appear in §2/§3 prose (not just §5); no fuzzy words ("approximately", "roughly", "about", "around", "~"); zero fuzzy hedging; §4/§5 tables column-conformant.

## Step 5: Generate Unit Tests — 2026-08-15T02:50:00.000Z

Done. Summary of the generated suite for task 1924:

## Test files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1924_legal_aid_intake_case_assignment/`)

**test_helpers/** — Stage 1 infrastructure:
- `types.py` (enums + TypedDicts; auxiliary entities `VenueRule`/`TimeEntry`/`SatisfactionSurvey`/`UnmetNeedRecord`/`WaitlistEntry` carry only `id`+`created_at`, per PRD §2.5)
- `api_client.py` (one method per endpoint; subclasses `GenericApiClient`)
- `api_errors.py` (all 42 error IDs + HTTP map, registered via `set_error_http_status_map`)
- `assertions.py` (per-entity assertions + `assert_grant_ledger_invariants` for the PRD §2.11 conservation law)
- `constants.py` (FPL constants, caps, weights, temporal windows)
- `factories.py`, `test_users.py` (per-instance `make_<role>_headers` builders for the five entity-backed roles; opaque shared constants for GrantsManager/ProgramDirector)
- `fixtures.py` (composite chains: `create_eligible_application`, `create_openable_application`, `setup_open_case`, `setup_assigned_case`, `setup_closed_advice_case`, `set_clock`, `run_sweep`)
- `__init__.py` (barrel export)

**test_suite/** — `conftest.py` + 10 test files, **109 tests total**, all collecting cleanly under pytest.

## Per-queue counts
- **Queue A (Difficulty): 20/20 instances covered, each with ≥2 tests** (one instance, `grant_reservation_rounding_order_per_case`, has 3). Per-rule: dual_variant_calc [2,2], combinatorial_formula [2,2,3], non_linear_state_machine [2,2,2], transitive_cascade [2,2], priority_pair_validation_conflict [2,2], boundary_precision_check [2,2], cross_entity_state_dependency [2,2], resource_temporal_overlap [2,2], compensating_invariant [2,2].
- **Queue B (Corner): 61/62 non-stub instances covered with ≥1 test each** (entities 8/8, state_machines 12/12, calculations 7/7, validations 26/26, errors 2/2, rbac 5/5, cross_cutting 6/6, consistency_model 0/1). The 5 `excluded_because:` stubs under `errors` were correctly NOT translated (their `difficulty_instance` pointers all resolve to real §1.8 instances whose tests carry the assertions).

## Instances skipped (with reason)
- **Corner/consistency_model/immediate_read_after_create_consistency** — SKIPPED on the PRD-first filter. The instance's distinguishing aspect is immediacy ("fully readable … in the very next GET — no lag, no reconciliation delay"). PRD.md contains no sentence stating immediate read-after-write consistency; `complexity_profile.consistency_model: immediate` is scaffold-only. A PRD-only implementer could ship an eventually-consistent variant, so the asserted outcome fails unique derivability. Gap left as gap — no test emitted, no skip/xfail marker.

## Self-audit results
- **Stage 1**: all nine helper files present; `common_fields: false` branching honored in TypedDicts; entity-backed identity threading via `make_<role>_headers(entity.id)` throughout fixtures and tests; pyflakes-clean; compiles.
- **Stage 2**: every one of the 109 tests has a docstring ending with exactly one `Design: Difficulty/...` or `Design: Corner/...` line copied verbatim from the source YAML and resolving to a real instance (C4 verified programmatically, 0 problems); every quoted citation was verbatim-grep-verified against PRD.md (0 failures after fixing 16 initially elided quotes to full non-abbreviated sentences); no `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold/table references in comments or docstrings; no freelance tests beyond the two design indices.

## Step 6: Generate Implementation — 2026-08-15T02:50:00.000Z

Done. The implementation is complete and verified end-to-end (three smoke batches, 100+ assertions, all passing after fixing one missing error constant).

## Summary

### File list — `tasks/task_1924_legal_aid_intake_case_assignment/workspace/implementation/`
- `start.sh` (executable), `requirements.txt` (`Flask>=3.0,<4.0`)
- `app.py` — app factory, blueprint registration, global request lock, error handlers (ApiError → envelope; 404/405 → `ERR_NOT_FOUND` envelope; catch-all 500), runs `0.0.0.0:$PORT` (default 10000)
- `db.py` — empty in-memory store, logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), UUID minting, ISO-8601 3-fractional-digit timestamp formatting
- `errors.py` — `ApiError` + the full 41-error catalog with exact ids/statuses
- `response.py` — envelope: `{meta: {api_request_id, api_request_timestamp}, response_type: object|array|error, data}`; list responses add `limit/offset/total_count/has_more` in `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (`ERR_UNAUTHENTICATED` 401) + per-endpoint RBAC (`ERR_UNAUTHORIZED_ROLE` 403)
- `validators.py` — JSON body parsing, unknown-field rejection, typed field validators (int rejects bool, enum membership, ranges, ISO dates), pagination parsing (limit default 10 clamped [1,100], offset default 0)
- `services/`: `calc.py` (pinned calculations, `Decimal` + `ROUND_HALF_UP`), `derived.py` (load/count/ledger derivation), `common.py` (lookup/stamp/list helpers), `serialize.py`, `case_ops.py` (shared close side-effects), `enums.py`
- `routes/`: `clients`, `applications` (+ conflict-check create/list, open-case gauntlet), `conflict_checks`, `cases` (+ assign/hold/resume/close, nested time-entries/referrals/surveys), `staff` (+ caseload), `panel`, `referrals`, `grants` (+ utilization, nested reports), `reports`, `venue_rules`, `records` (time-entries/unmet-need/waitlist reads), `ops` (clock + sweep)

### Boot contract
`start.sh` guards the dependency install (`python3 -c "import flask"` — a no-op once Flask is present, so per-test reboots don't thrash pip), then `exec python3 app.py` in the foreground, binding `0.0.0.0:$PORT` (verified live: boots and serves within ~2s from a fresh process).

### Storage strategy
Pure in-memory dicts in `db.py`, completely empty at boot (no seeding anywhere), reset automatically on every per-test-server restart. A single `RLock` acquired per request serializes all access.

### Notable design decisions
- **Derived, not stored, aggregates**: `weighted_open_units`/`open_case_count` (attorney, OPEN cases only), `active_referral_count` (ACCEPTED referrals), and the grant ledger buckets (`reserved` = sum over `GRANT_RESERVED|GRANT_FROZEN` cases; `spent` = sum over `GRANT_SPENT`) are recomputed from source records at read time. This makes every cascade (assign/reassign, hold/resume, close, grant-suspend links 1–3, sweep auto-close) correct by construction; cascades still bump `updated_at`/`version` on every touched entity.
- **State machines**: IntakeApplication (incl. docs loop, rescreen with OCC, waitlist enqueue/promote, withdrawal unmet-need rules — no record from `INELIGIBLE`), ConflictCheck (SoD recusal, waiver-reason requirement), Case dual axis (`status` × `funding_status`), Referral (half-open `[start,end)` window overlap; adjacency allowed), GrantProgram (closed-interval same-funder overlap where boundary-touching counts), GrantReport (DRAFT→SUBMITTED→ACCEPTED/RETURNED→revise recompute; one live DRAFT/SUBMITTED per program).
- **Pinned calculation order**: per-case grant reservation rounded half-up to whole cents *before* summation (rate 33,333 → advice case reserves exactly 13,333); priority score `min(100, round2(base × min(1+0.15n, 1.75) + urgency))`; both poverty percentages stored at every screen but only the standard variant (125.00 inclusive cap + benefits auto-pass) drives `eligibility_determination`.
- **Open-case gauntlet order follows PRD §3.5** (which overrides scaffold priority numbers where they disagree): self-screening SoD → latest conflict check CLEAR/WAIVED → recency (`valid_until < now` is stale; equality is not) → duplicate open case → EXTENDED permission (stored `priority_score ≥ 60.00` + `extended_eligible`) → EXTENDED capacity pool → grant gates (period, case type, county, income cap, budget).
- **Strict deadline semantics**: sweep steps in pinned order (conflict expiry → referral expiry → advice auto-close with full close side effects → waitlist waterfall with skip-no-blocking against post-auto-close capacity); a deadline exactly equal to the clock does not trigger (verified by test).
- **Validation precedence**: auth → role → path ids → ownership (time-entry/close 403s before body shape) → shape (unknown fields, enums, ranges) → body FKs → state → OCC (`expected_case_version`/`expected_application_version` → 412) → SoD → business rules, per PRD §2.7.
- One judgment call where the catalog is silent: resolving a conflict check that is not `POTENTIAL_CONFLICT` returns `ERR_CONFLICT_UNRESOLVED` (409), the only conflict-state error defined.

## Step 7: Run Tests and Iterate — 2026-08-15T03:05:00.000Z

## Summary

**Result: all 8 parallel rounds pass — 109/109 tests in every round.**

- **Iterations run:** 2 sweeps (sweep 1: 107/109 in all 8 rounds; sweep 2 after fixes: 109/109 × 8).

- **Pre-flight error-catalog check:** PRD §5 lists exactly 42 error codes. `implementation/errors.py` contains all 42 with correct HTTP statuses, plus `ERR_VENUE_RULE_CONFLICT` (409) declared in PRD §3.9 prose — the catalog was complete; the generator's "41-error" remark in its summary was an undercount, not a real gap. No implementation error changes needed.

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1924_legal_aid_intake_case_assignment/test_helpers/api_errors.py` — added the missing `ERR_VENUE_RULE_CONFLICT` member to the `ApiErrorId` enum and its `409` entry in `HTTP_STATUS_CODES`. The enum had been generated only from the PRD §5 table, omitting this prose-declared error (PRD §3.9: "The pair of `county` and `case_type` is unique across rules; a duplicate creation is rejected with `ERR_VENUE_RULE_CONFLICT` (HTTP 409)"). This caused `AttributeError` in `test_venue_rule_duplicate_rejected`; the implementation already returned the correct error.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1924_legal_aid_intake_case_assignment/test_suite/test_04_case_assignment_caseload.py` — `test_open_case_count_heads_vs_weights_second_reader`: setup opened a second case for the **same client and same case_type** while the first was `OPEN`, violating PRD §3.5 step 4 (`ERR_DUPLICATE_OPEN_CASE`), which the implementation correctly enforced. Fixed the setup to use a distinct second client and open the pending case as `ADVICE_ONLY` (the original `EXTENDED` would also have tripped the §3.5 step 5 priority gate: base 30 + urgency 0 = 30.00 < 60.00). The asserted rule (PRD §2.10: `PENDING_ASSIGNMENT` contributes nothing to `open_case_count`/`weighted_open_units`) is unchanged.

- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful in both failures; both were test-artifact bugs.

## Step 8: Finalize PRD — 2026-08-15T03:12:00.000Z

Done. `PRD_FINALIZED.md` is written with exactly one minimal patch.

**Line counts and %-delta**
- PRD.md: 359 lines; PRD_FINALIZED.md: 360 lines; +1 line (+0.28%).

**Changes (one total)**
- §5 Error Code Catalogue — insert — added the missing row `| ERR_VENUE_RULE_CONFLICT | 409 Conflict |` immediately after `ERR_VENUE_UNDETERMINED` (placement mirrors the ordering in `errors.py`). The error was already declared in PRD §3.9 prose and already named in the §2.7 step-10 cascade, but absent from the §5 table — the gap that produced the `AttributeError` in `test_helpers/api_errors.py` — `implementation/errors.py:20`, `implementation/routes/venue_rules.py:31`.

**Per-edit pre-edit search log**
- (a) Subject: the `ERR_VENUE_RULE_CONFLICT` error — its declaration, HTTP status, and every raise site, to confirm the new §5 row describes all of them.
- (b) Paths enumerated: repo-wide grep for `ERR_VENUE_RULE_CONFLICT` across `implementation/` returned exactly two references — `implementation/errors.py:20` (declaration, 409) and `implementation/routes/venue_rules.py:5,29–32` (raised on duplicate `(county, case_type)` creation in `POST /venue-rules`, after shape validation, ProgramDirector-only). Full-catalogue diff of `errors.py` (43 entries) against the PRD §5 table confirmed this was the sole divergence; all other 42 IDs/statuses matched. PRD-internal consistency checked: §2.7 step 10 (line 112) already names the error, §3.9 (line 230) already declares it at HTTP 409. Also read `implementation/routes/applications.py:234–309` (the §3.5 gauntlet) to confirm the second step_7_diff item (`test_04_case_assignment_caseload.py`) was a pure fixture bug — the implementation enforces `ERR_DUPLICATE_OPEN_CASE` (step 4) and the stored-`priority_score` EXTENDED gate (step 5) exactly as the PRD already pins, and §2.10 already states `PENDING_ASSIGNMENT` contributes nothing to caseload. No PRD silence there, so no edit.
- (c) Wording adjustment: none — §5 rows carry only error ID and HTTP status, so the inserted row cannot mis-describe any enumerated path; 409 matches both the `errors.py` declaration and the existing §3.9 prose.

No other edits: step_7_diff recorded zero implementation fixes and zero test deletions; the test_helpers enum gap traces to this same §5 omission (now fixed at the source). Post-edit verification: the finalized §5 catalogue now matches `implementation/errors.py` exactly (43/43 rows), and `diff PRD.md PRD_FINALIZED.md` shows only the single inserted line.

File: `/home/ubuntu/github/CodingPRD/tasks/task_1924_legal_aid_intake_case_assignment/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-15T03:35:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1924_legal_aid_intake_case_assignment/workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`, which exists, then edited in place).

**Stats**
- Source: `PRD_FINALIZED.md` — 360 lines, 57,936 chars. `PRD_COMPLETED.md` — 362 lines, 61,776 chars. Char-delta: **+3,840**.
- Counts: **33 ambiguity-pins**, **5 mismatch-revisions**. No new sections; all changes are in-paragraph inserts/revisions.

**Mismatch revisions (5)**
- §3.2 — revise — mismatch — `withdrawal_reason` was "optionally recording"; impl validates it but never stores it (not in `application_json`) — `routes/applications.py:214-231`
- §3.4 — revise — mismatch — waitlist ranking claimed "no further tie-breakers"; impl breaks `created_at` ties by creation sequence (`_seq`) — `services/common.py:57-61`, `routes/ops.py:63-65`
- §2.9 — revise — mismatch — `income_cap_percentage` removed from the round-half-up-to-2dp list; impl stores it exactly as supplied (`req_number`, no `round2`) — `routes/grants.py:47`
- §3.7 — revise — mismatch — "assigned_attorney_id remains null while pro bono–placed" replaced: acceptance leaves staffing untouched (a `PENDING_ASSIGNMENT` case keeps null; an already-assigned case keeps its attorney) — `routes/referrals.py:90-101`
- §3.8 — revise — mismatch — `hours` "with two decimal places" → "a JSON number from 0.25 to 24.00, both bounds inclusive" (no decimal-place enforcement exists) — `routes/cases.py:209-211`

**Ambiguity pins (33)**
- §2.1 — insert — ambiguity — missing *or empty* auth headers → `ERR_UNAUTHENTICATED` — `middleware.py:29`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not the wall clock — `response.py:14-18`, `db.py:36-37`
- §2.2 — insert — ambiguity — unknown path / unsupported method → `ERR_NOT_FOUND` (404); unexpected failure → `ERR_INTERNAL` (500), same envelope — `app.py:44-55`
- §2.3 — insert — ambiguity — out-of-range/unparseable `limit`/`offset` are clamped (limit→[1,100], offset→≥0, unparseable→default), not rejected — `validators.py:194-208`
- §2.3 — insert — ambiguity — list sort ties at equal `created_at` broken by creation sequence — `services/common.py:62`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` explicitly added to the clock-stamped timestamp list — `services/common.py:15-33`
- §2.7 step 5 — insert — ambiguity — non-JSON / non-object body → `ERR_INVALID_REQUEST` — `validators.py:11-22`
- §2.7 step 10 — insert — ambiguity — `ERR_STAFF_NOT_ACTIVE` added to the business-constraint ordering (was absent from the cascade) — `routes/cases.py:97`
- §2.7 — revise — ambiguity — workflow-pinned-order exception extended to §3.6/§3.7 (impl checks panel capacity before window overlap on respond) — `routes/referrals.py:67-83`
- §2.10 — insert — ambiguity — `utilization_pct` = `weighted_open_units`/`max_units`×100, half-up 2dp — `services/serialize.py:250-258`, `services/calc.py:72-75`
- §2.11 — insert — ambiguity — grant `utilization_pct` = (`reserved`+`spent`)/`total_budget_cents`×100, half-up 2dp, 0.0 at zero budget — `services/serialize.py:261-271`
- §3.1 — insert — ambiguity — `vulnerability_factors` stored exactly as supplied, duplicates included (each entry counts toward the multiplier) — `routes/clients.py:44-46`, `services/calc.py:47-50`
- §3.1 — insert — ambiguity — client PATCH: JSON-null field treated as omitted — `routes/clients.py:85-108`
- §3.1 — insert — ambiguity — financial field re-sent with its existing value triggers no cascade — `routes/clients.py:110-111`
- §3.1 — insert — ambiguity — cascade-reset applications also bump their own `version` — `routes/clients.py:121-127`
- §3.3 — insert — ambiguity — check state lives in `result`, overwritten in place by resolution and expiry — `routes/applications.py:354-368`, `routes/ops.py:33-38`
- §3.3 — insert — ambiguity — resolving a non-`POTENTIAL_CONFLICT` check → `ERR_CONFLICT_UNRESOLVED` (409) — `routes/conflict_checks.py:34-36`
- §3.3 — insert — ambiguity — recusal check fires before the `waiver_reason` requirement — `routes/conflict_checks.py:38-44`
- §3.3 — insert — ambiguity — `waiver_reason` must be non-blank and is stored only for `WAIVED` — `routes/conflict_checks.py:41-49`
- §3.4 — insert — ambiguity — enqueue-waitlist responds with the updated application object, not the entry — `routes/applications.py:211`
- §3.5 — insert — ambiguity — "latest conflict check" ties broken by creation order — `services/derived.py:78-83`
- §3.5 — insert — ambiguity — successful open moves the application to `OPENED` — `routes/applications.py:335`
- §3.5 — insert — ambiguity — case register filters: `application_id`, `grant_program_id`, `assigned_attorney_id`, `assigned_paralegal_id`, `status`, `funding_status`, `placement` — `routes/cases.py:50-60`
- §3.6 — revise — ambiguity — a supplied `supervising_attorney_id` must reference an `ATTORNEY` for *any* staff type (required only for `PARALEGAL`) — `routes/staff.py:36-46`
- §3.6 — insert — ambiguity — staff update mutable fields enumerated (`staff_type` immutable); null `supervising_attorney_id` actively clears; `max_units` may be set below current load (negative `available_units`) — `routes/staff.py:105-157`
- §3.6 — revise — ambiguity — assignment sets `assigned_paralegal_id` to the supplied value, clearing any prior paralegal when absent — `routes/cases.py:118-119`
- §3.7 — insert — ambiguity — panel-member status enum is `ACTIVE`/`SUSPENDED`/`INACTIVE`; update fields and null-omitted semantics pinned — `services/enums.py:15`, `routes/panel.py:61-93`
- §3.7 — insert — ambiguity — referral service dates are ISO `YYYY-MM-DD` strings — `routes/referrals.py:54-60`
- §3.8 — insert — ambiguity — `work_date` is an ISO `YYYY-MM-DD` date string — `routes/cases.py:213`
- §3.8 — insert — ambiguity — any closure naming an assigned attorney refreshes that attorney's `updated_at`/`version` even when load is unchanged — `services/case_ops.py:22-25`
- §3.9 — insert — ambiguity — grant `period_start`/`period_end` are ISO `YYYY-MM-DD` date strings — `routes/grants.py:40-41`
- §3.9 — revise — ambiguity — report `return_reason` must be non-blank (whitespace-only rejected) — `routes/reports.py:64-66`
- §3.9 — insert — ambiguity — report revision recomputes aggregates but retains `period_label`, `generated_by_user_id`, and recorded `return_reason` — `routes/reports.py:74-87`
- §3.9 — insert — ambiguity — grant-freeze cascade refreshes `updated_at`/`version` of every frozen case and its assigned attorney — `routes/grants.py:107-117`

Everything else in the implementation (endpoint table, roles per endpoint, gauntlet order, sweep step order, reservation formula and pinned rounding, ledger conservation, state machines, OCC scope, error catalogue) was verified against the code and already pinned uniquely by the PRD — no changes needed there.
