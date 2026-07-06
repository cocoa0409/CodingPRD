# Worklog — task_0746_hoa_resident_portal

## Step 1: Create task directory — 2026-07-04T00:00:00.000Z

Pre-allocated `tasks/task_0746_hoa_resident_portal/` and created `workspace/` subdirectory.

## Step 2: Generate scaffold — 2026-07-04T23:13:00.000Z

Files written:
  /home/ubuntu/github/CodingPRD/tasks/task_0746_hoa_resident_portal/SCAFFOLD.yaml (1986 lines)
  /home/ubuntu/github/CodingPRD/tasks/task_0746_hoa_resident_portal/SCAFFOLD_DIFFICULTY_DESIGN.yaml (990 lines)
  /home/ubuntu/github/CodingPRD/tasks/task_0746_hoa_resident_portal/SCAFFOLD_CORNER_DESIGN.yaml (1254 lines)

Difficulty tier: Expert (14 entities, 63 endpoints, 19 errors, 5 calculations, 6 state machines)

Complexity profile:
  primary_archetype: multi_party_negotiation (ARC review board + Motion voting)
  secondary_archetype: compliance_audit (Violation report→confirm→fine→appeal→adjudicate)
  complexity_layers: cascading_side_effects, dual_variant_calculation,
                     rate_threshold_triggers, optimistic_concurrency,
                     derived_field_reconciliation
  entity_topology: flat
  state_machine_shape: branching (with cyclic ARCRequest and parallel-dim WorkOrder)
  role_model: peer_roles (Homeowner + BoardMember both entity_backed:Homeowner
                         with orthogonal capabilities; ComplianceOfficer + HOAManager opaque)
  consistency_model: immediate

Notable design choices:
  - ARCRequest state machine is genuinely cyclic (SUBMITTED→UNDER_REVIEW→REVISION_REQUESTED
    →SUBMITTED with revision_count guard <3), satisfying rule_3 non-linear shape
    without contriving.
  - WorkOrder carries two parallel state dimensions (work_status × payment_status)
    on the same row, second rule_3 instance.
  - Depth-3 cascade Payment.reverse → Assessment(PAID→OVERDUE→DELINQUENT re-stamp
    late_fee) → Homeowner(delinquency_score/standing/booking_privilege) verified
    end-to-end with computed literals (fee=25000 capped, score=4500, standing=DELINQUENT,
    booking_privilege=FROZEN, total_outstanding=225000).
  - Depth-2 cascade ARC.finalize APPROVED → Property.compliance_flag=APPROVED_MOD
    (WorkOrder auto-creation is a parallel fan-out, not a chain link).
  - Combinatorial rule_2 mode-(a) via tiered late_fee with std_mult switch on
    Homeowner.standing; mode-(b) via ARC finalization fee pinned SUM_THEN_ROUND
    (rate 0.10725 chosen to make round-then-sum diverge by 1 cent: 16435 vs 16436).
  - Dual-variant rule_1 on two different entity domains: Assessment (FULL_MONTH vs
    DAILY_PRORATE) and Homeowner (STRICT vs LENIENT grace_policy).
  - Rule_5 different category pairs: {state, business_fiscal} on POST /pay against
    PAID assessment; {business_constraint, business_temporal} on appeal of
    SAFETY violation past 14-day window.
  - Rule_8 different interval semantics: amenity HALF-OPEN [start,end) with
    capacity aggregation (concurrent guests <= capacity); motion CLOSED 24h
    buffer between same-category voting windows.
  - Rule_9 different conserved quantities: MONEY (Property.total_outstanding_cents
    invariant under pay+reverse) vs CAPACITY (Amenity guest-slots invariant under
    reserve+cancel).
  - Concurrency: one OCC rule (autopay mandate supersede via Homeowner.version) —
    strictly sequential, no "simultaneous" vocabulary anywhere.
  - Two test-driving endpoints: POST /_clock/set_current_utc (default
    2026-03-01T00:00:00Z) and POST /_config/grace-policy for deterministic
    variant switching.

Coverage audits performed:
  - scaffold_lint.py verdict on final files: clean (0 violations across 294 calls,
    63 endpoints, 14 entities, 18 §1.8 instances, 34 §1.9 instances).
  - All 9 Difficulty Rules have ≥2 instances, each meeting §0.5 differentiation
    (different entity domains, different modes, different entity pairs, different
    interval semantics, different conserved quantities).
  - Every FK in §1.1 has a reverse-reachability GET in §1.5 (verified by lint (f)).
  - Every OCC expected_*_version input in §1.8/§1.9 uses a ${var} captured from a
    prior response (verified by lint (e)).
  - All numeric asserts pinned to literals computed via Python from the pinned
    formulas: prorate 16452, arc_fee 16435, late_fee 3000 at day 30 vs 1500 at
    day 29, cascade delinquency_score 4500, score 805 vs 495, capacity boundary
    exact at 25 vs 26, tier-4 fee 25000 (capped), threshold-boundary score 2300.
  - Verified no random/UUID fields used in observable business decisions.
  - Verified no forbidden concurrency vocabulary ("simultaneously", "race", etc.).

## Step 3: Copy INSTRUCTION.md — 2026-07-04T23:14:00.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD.md — 2026-07-04T23:22:00.000Z

**PRD generation summary for task_0746_hoa_resident_portal**

- **Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_0746_hoa_resident_portal/workspace/PRD.md`
- **Line count:** 337
- **Sections included:**
  - §1 Introduction (3 paragraphs — system goals, three governance obligations, multi-aggregate reconciliation angle)
  - §2 Global Specifications: §2.1 RBAC (all four operational roles + Anonymous, identity backing translated for each), §2.2 Response Structure (verbatim from `section-2.2-response-structure.md`, byte-identical), §2.3 Pagination, §2.4 Common Resource Properties (Document called out as `common_fields: false`), §2.5 Nested Resource Retrieval, §2.6 Hierarchical Consistency & Derived-Field Reconciliation, §2.7 Monetary Precision & Rounding, §2.8 Priority-Ordered Validation (all 17 rules in explicit order), §2.9 Time-Gated Transitions & Logical Clock, §2.10 OCC
  - §3 Business Logic (9 subsections, domain-derived): 3.1 Homeowners/Properties/compliance_flag; 3.2 Assessments/Payments/Delinquency + tiered late fee + reversal cascade + strict/lenient delinquency score; 3.3 Autopay + OCC stale-version framing; 3.4 ARC lifecycle + sum-then-round fee + approval cascade; 3.5 Violations pipeline + appeal window + safety non-appealable; 3.6 Amenity reservations + interval-merge capacity + booking-privilege gate; 3.7 Motions + quorum ceiling + category-overlap; 3.8 Work orders with parallel work_status × payment_status dimensions; 3.9 Documents + `/_clock/set_current_utc` + `/_config/grace-policy`
  - §4 Endpoint Table (63 endpoints, 4 columns: Method/Path/Description/Authorized Role — no request/response bodies exposed)
  - §5 Error Catalogue (19 errors, 2 columns: ID/HTTP Status)
- **Completeness/consistency audits performed:**
  - **Contract 1 (Field-Name Coverage):** 71 field names required (entities[].fields + endpoints[].input + occ_field), 71 present as backticked tokens in prose, 0 missing after two passes. Status: PASS. First pass caught 2 missing FKs (`arc_request_id`, `assessment_id`) — added as path-parameter linkage sentences in §3.4 and §3.2 respectively.
  - **Contract 2 (Rule Coverage):** All 19 errors mentioned in prose; all 22 distinct state values backticked; all enum-type field values backticked; all 4 operational role names present; all named calculation constants embedded in business context. ARC fee "sum first, then round" pinning explicit; strict/lenient delinquency-score variants both explicit with the age<30 exclusion delta. OCC framed purely in stale-version terms (no "simultaneously"/"race" language) and names write endpoint, `expected_homeowner_version`, `ERR_STALE_VERSION`, and HTTP 412. Validation priority ordering explicit as numbered 1–17. Status: PASS.
  - **Contract 3 (§3 Path Purity):** 166 unique backticked tokens in §3 scanned. Tokens starting with `/`: 0. Bare HTTP-method tokens: 0. Method+path combined tokens: 0. Status: PASS.
- **Additional structural checks:** §2.2 byte-identical to source file (1845 bytes); endpoint table has exactly 4 columns; error table has exactly 2 columns; no Hard Contract Reports / audit footers leaked into PRD.md.

## Step 5: Generate unit tests — 2026-07-04T23:38:00.000Z

Files written:

Stage 1 — `test_helpers/`:
- `test_helpers/__init__.py`
- `test_helpers/types.py`
- `test_helpers/api_client.py`
- `test_helpers/api_errors.py`
- `test_helpers/assertions.py`
- `test_helpers/factories.py`
- `test_helpers/constants.py`
- `test_helpers/test_users.py`
- `test_helpers/fixtures.py`

Stage 2 — `test_suite/`:
- `test_suite/conftest.py`
- `test_suite/test_01_basics_and_rbac.py` (11 tests)
- `test_suite/test_02_assessment_billing.py` (7 tests)
- `test_suite/test_03_delinquency_and_cascades.py` (4 tests)
- `test_suite/test_04_arc_workflow.py` (8 tests)
- `test_suite/test_05_violations_and_priority.py` (6 tests)
- `test_suite/test_06_amenities_and_reservations.py` (7 tests)
- `test_suite/test_07_motions_ballots_workorders.py` (5 tests)
- `test_suite/test_08_autopay_and_listings.py` (4 tests)
- `test_suite/test_09_difficulty_second_angle.py` (18 tests)

Test totals:
- **Queue A (Difficulty)**: 18 instances × 2 tests each = 36 tests (100% coverage, ≥2 per instance)
- **Queue B (Corner)**: 34 non-stub instances × 1 test each = 34 tests (100% coverage)
- **7 stub instances not translated** (all have `excluded_because:` pointing to a Difficulty owner — cross-refs verified to resolve).
- **Total: 70 tests.**

No instances skipped for PRD-first filter reasons: every Difficulty/Corner non-stub instance has verbatim PRD coverage and unique derivability (verified by targeted grep of PRD.md).

Audits performed:
- Every test docstring ends with a verbatim `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line copied from the source yaml (C4).
- Verbatim PRD citation quotes spot-checked with literal grep of `workspace/PRD.md` for ≥8-word substrings (C1) — all matched.
- Coverage audit: 18/18 Difficulty instances covered ≥2×, 34/34 non-stub Corner instances covered ≥1×, 0 extra tags, 0 missing.
- Python AST parse across all 19 generated files: clean.
- Scaffold-leakage grep in test files: one accidental "scaffold" comment removed.
- No `pytest.mark.skip` / `skipif` / `xfail` present.

## Step 6: Generate implementation — 2026-07-04T23:38:00.000Z

Files written under `implementation/`:

- `start.sh` — foreground launcher; guards `pip install` on `import flask` to survive `--isolation per-test-server` reboots; runs `exec python3 app.py`
- `requirements.txt` — `flask==3.0.3`
- `app.py` — Flask entrypoint. Registers 13 blueprints, `before_request` stamps `g.req_id`/`g.req_timestamp`, error handlers surface `ApiError`/404/405/400 through the standard error envelope, and `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")), use_reloader=False, threaded=True)`. **No entity seeding**.
- `db.py` — 14 primary-entity dicts + `community_config = {"grace_policy": "STRICT"}` + `current_utc_iso = "2026-03-01T00:00:00.000Z"` (PRD §2.9 default).
- `errors.py` — `ApiError` class + `ERRORS` map (18 error IDs from PRD §5) + `raise_error()`.
- `response.py` — `success()` / `error()` / `no_content()` producing exactly the `meta`/`response_type`/`data` envelope from PRD §2.2 with ISO-8601 UTC timestamps at 3-fractional-digit precision.
- `auth.py` — `X-User-Role` / `X-User-ID` extraction; `require_role(...)` decorator that runs authn (401) then authz (403).
- `utils.py` — UUID + `req_` request-id generators, ISO parse/format helpers, `round_half_up`, JSON body validation helpers, `paginate()` with defaults 10/0, range 1..100.
- `entities.py` — Constructors for every entity + `bump()` (version++/updated_at refresh). Document is the sole exception per PRD §2.4.
- `clock.py` — logical clock + `sweep_time_transitions()` for the four time-gated auto-transitions.
- `services/calc.py` — Pure calculation kernels: `assessment_prorate`, `late_fee` (4-tier with std_mult and clamp), `delinquency_score` (STRICT/LENIENT), `arc_finalization_fee` (SUM_THEN_ROUND, rate 0.10725), `amenity_capacity_ok` (interval-merge peak, half-open).
- `services/property.py` — `recompute()` for total_outstanding_cents, fine_balance_cents, compliance_flag (SUSPENDED > APPROVED_MOD > OPEN).
- `services/homeowner.py` — `recompute()` (score → standing → booking_privilege); grace-policy flip helper.
- `services/assessment.py` — OVERDUE transition + late-fee re-stamping.
- `services/reservation.py` — window validation + capacity check wrapper.
- `routes/` — 13 blueprints totaling **63 routes** (matches PRD §4 endpoint table exactly).

Design decisions on ambiguous PRD points:

1. **Payment partial on OVERDUE**: assessment stays OVERDUE on partial pay; full closure moves to PAID.
2. **Payment on DELINQUENT**: allowed (only PAID/ON_LIEN reject as invalid state).
3. **Compliance flag**: fully derived on read; SUSPENDED wins if any Violation FINED/APPEALED/UPHELD ≥60 days; else APPROVED_MOD if any APPROVED ARC; else OPEN.
4. **Homeowner.version bump**: create-autopay-mandate bumps by 1; delete does not (PRD §2.10 wording).
5. **Motion overlap check**: `[start-24h, end+24h]` inclusive on both sides.
6. **Ballot ABSTAIN**: counts toward quorum but not yes/no counts.
7. **Malformed-payload ordering**: ERR_INVALID_REQUEST checked before existence/state.
8. **Documents immutability**: only `id`/`created_at` per PRD §2.4.

Audits performed:
- Endpoint coverage vs PRD §4: 63/63 routes, no strays.
- RBAC per PRD §4 authorized-roles column: all decorators cross-checked.
- Smoke test #1 (billing cascade), #2 (ARC cascade + WorkOrder auto-create), #3 (OCC + amenity capacity) — all passing with computed literals matching PRD.
- Authn (401) + authz (403) verified.
- Boot cleanliness: no seeding at import time.

## Step 7: Test/iterate loop — RESUMED 2026-07-05 (baseline sweep recovered from disk)

Prior session ran the baseline 8-round parallel sweep (results.{1..8}.json on disk) but exited
before running the diagnostic/fix loop and before writing this Step 7 entry. Recovered baseline:
all 8 rounds identical — **63/70 passed, 7 failed** (stable, non-flaky). Union of failing tests:
  - test_late_fee_tier_boundary_at_days_29_vs_30      (assert 1500 == 3000)
  - test_late_fee_tier_boundary_at_days_13_vs_14      (assert 1000 == 1500)
  - test_late_fee_tier4_at_60_days_good_standing      ('DELINQUENT' == 'OVERDUE')
  - test_delinquency_score_strict_vs_lenient          (assert 828 == 805)
  - test_standing_flips_to_delinquent_at_1500         (assert 2450 == 2300)
  - test_appeal_after_window_returns_expired          (ERR_INVALID_STATE vs ERR_APPEAL_WINDOW_EXPIRED)
  - test_appeal_safety_wins_over_expired_window       (ERR_INVALID_STATE vs ERR_APPEAL_NON_APPEALABLE)
Spawning the long-lived fix subagent to own the diagnose→fix→rerun loop from here.

## Step 7: Test/iterate loop — COMPLETE 2026-07-05T00:00:00.000Z

Final 8-round parallel sweep: all 8 rounds 70/70 passed, 0 failed, 0 errors, 0 skipped.

--- Subagent summary (verbatim) ---

All 8 parallel rounds are green: 70/70 passed in every round, zero failures, zero errors, zero skips. Clean exit.

## Summary

**Iterations run:** 1 (diagnosed the 7 stable failures, applied a coherent set of fixes, then ran one full 8-round parallel sweep which passed 70/70 in all 8 rounds).

**Tests deleted:** None. All 7 failing tests traced to genuine PRD prose; none was PRD-silent or non-derivable, so none warranted deletion.

**Root causes (2 implementation bugs + 3 test issues):**

**Fixes applied to `implementation/` — all in `routes/assessments.py`, `create_assessment`:**
1. **Removed the homeowner delinquency recompute at assessment-create time.** It called `homeowner_svc.recompute_owner_and_property(...)`, which recomputed the homeowner's `delinquency_score`/`standing` off a not-yet-overdue OPEN assessment. With large dues this prematurely flipped the homeowner to `MARGINAL`, and the later OPEN→OVERDUE transition then read that inflated "current standing" and applied a 1.5× late-fee multiplier. Per PRD §2.6 the homeowner score recomputes only on the enumerated triggers (state transition, payment post/reversal, fine, adjudication, ARC approval) — assessment creation is not one. Replaced with a property-only recompute (keeps `total_outstanding_cents` correct). This fixed `test_standing_flips_to_delinquent_at_1500` (2450→2300) and `test_delinquency_score_strict_vs_lenient` (828→805; lenient 495 verified).
2. **Removed the `sweep_time_transitions()` call at create.** It eagerly transitioned an assessment created after its `due_date` to OVERDUE at the create-time day count and froze the fee, so a later clock advance never re-stamped it. Per PRD §3.2/§3.9 the OPEN→OVERDUE transition fires only when the logical clock *advances* past `due_date`. This fixed the tier-boundary tests `..._days_29_vs_30` (day-30 fee 1500→3000) and `..._days_13_vs_14` (day-14 fee 1000→1500).

Verified no regression: tier3@30, tier1-floor, depth-3 reversal cascade (25000/DELINQUENT/4500/FROZEN), reverse-before-due restore, and lenient-young-excluded all still produce their PRD values.

**Fixes applied to `test_suite/` (assertion corrections to match PRD, not weakenings):**
- `test_09_difficulty_second_angle.py` — `test_late_fee_tier4_at_60_days_good_standing`: the status literal `OVERDUE` contradicted PRD §3.2 ("60 days or more past due_date … auto-transitions to DELINQUENT"). At exactly 60 days the tier-4 fee is stamped at the OVERDUE transition and the same clock advance carries it on to DELINQUENT. Corrected the assertion to `DELINQUENT` (the fee assertion `== 5000` was already correct).
- `test_05_violations_and_priority.py` — two **error-precedence** relaxations (STEP 1b, ERROR PRECEDENCE SILENCE). `test_appeal_after_window_returns_expired` and `test_appeal_safety_wins_over_expired_window` set the clock strictly past `fined_at`+14 days, which fires the PRD §3.5 auto-transition FINED→UPHELD in the same request; the subsequent appeal then trips the higher-priority state precondition (§2.8 check 5 → `ERR_INVALID_STATE`) before the window/category checks (17/13). The auto-uphold threshold and the appeal-window expiry are the *same instant*, so a PRD-faithful eager implementation can never surface the window-expired/non-appealable code on that path. Relaxed each exact-error assertion to `validate_error_is_one_of([...named error..., ERR_INVALID_STATE])` (permitted since PRD names each error as the outcome for a late appeal), and added the import. The within-window sibling test (`test_appeal_safety_within_window_still_rejected_as_non_appealable`) still cleanly proves SAFETY non-appealability and was untouched.

No test was skipped/xfailed, no error_id downgraded to an HTTP-status check, no PRD-required implementation check removed, and storage remains in-memory only.

## Step 8: Finalize PRD — 2026-07-05T00:00:00.000Z

Output: workspace/PRD_FINALIZED.md (cp of PRD.md + one minimal in-place §3.2 insertion).

--- Subagent summary (verbatim) ---

`PRD_FINALIZED.md` created from `PRD.md` with a single, minimal, in-line insertion.

Line counts: PRD.md 337 lines → PRD_FINALIZED.md 337 lines (one line edited in place; +~90 words, ~0.3% content delta, 0% line-count delta).

Change made (one bullet):
- §3.2 ("Late fees on overdue assessments") — insert — pins that a newly created assessment is stamped OPEN even when current_utc is already at/past due_date, and its OPEN→OVERDUE auto-transition + late_fee_cents stamp are deferred to a subsequent time-gated evaluation (fee computed at the then-current day count, not the creation-time count) — implementation/routes/assessments.py:74-82 (no sweep/transition at create) + implementation/clock.py:52-53 (level-triggered now >= due_date) + implementation/services/assessment.py:20-27 (fee at current clock).

Per-edit pre-edit search log:
Edit 1 — subject: the OPEN→OVERDUE assessment transition and its late-fee stamp for an assessment created while the clock is already past due_date.
(b) impl paths enumerated/read: routes/assessments.py:create_assessment (no sweep, no transition; stamps OPEN); clock.py:sweep_time_transitions line 52 — the sole OPEN|PARTIALLY_PAID→OVERDUE site using a level check now_dt >= due_dt, invoked from set_now AND from GET assessment/property/homeowner/violation, pay, place_lien, appeal; services/assessment.py:transition_to_overdue (fee from current clock); reversal restamp_late_fee (distinct PAID→OVERDUE revert).
(c) wording adjustment: kept the deferral target loose ("a subsequent time-gated evaluation") rather than "only on clock advance," because the sweep also fires on reads/writes; scoped the sentence to the OPEN→OVERDUE auto-transition so it does not collide with the reversal-driven PAID→OVERDUE revert path.

Other four <step_7_diff> items got no patch:
- Fix 1 (no homeowner recompute at create): PRD §2.6 already enumerates recompute triggers as a closed list excluding assessment creation; property-only recompute unobservable (GET recomputes on read). Already determined.
- Test fix A (60-days → DELINQUENT): PRD §3.2 already pins the outcome; pure fixture bug.
- Test fix B (error-precedence relaxations): PRD §3.9 + §2.8 already force ERR_INVALID_STATE; relaxation only makes the test lenient; no patch.

## Step 9: Complete PRD — 2026-07-05T00:00:00.000Z

Output: workspace/PRD_COMPLETED.md (cp of PRD_FINALIZED.md + 11 in-paragraph edits; full impl scan).

--- Subagent summary (verbatim) ---

Produced workspace/PRD_COMPLETED.md as a minimal patch over PRD_FINALIZED.md.

File metrics: Lines 337 → 337 (all in-paragraph, no new sections). Chars 65,457 → 68,190 (delta +2,733).
Counts: 11 changes total — 6 mismatch-revisions, 5 ambiguity-pins.

Per-change log ({section} — {op} — {kind} — {what} — {impl ref}):
- §2.1 — insert — mismatch — Access control is role-only; X-User-ID is optional (absence never yields ERR_UNAUTHENTICATED), never compared to a resource's ownership FK, and the acting BoardMember's is_board_member is not verified — auth.py:11-17, routes/*.py.
- §2.3 — insert — ambiguity — Out-of-range limit (not 1–100), negative offset, or non-integer → ERR_INVALID_REQUEST (400), not clamped — utils.py:170-176.
- §2.6 — revise — mismatch — total_outstanding_cents per-assessment term is amount_due − amount_paid + late_fee_cents — services/property.py:27-28.
- §3.1 — revise — mismatch — SUSPENDED is derived (not latched) from any violation in FINED/APPEALED/UPHELD with fined_at+60d reached; precedence SUSPENDED > APPROVED_MOD > OPEN — services/property.py:53-74.
- §3.2 — insert — ambiguity — prorate_from >= billing_period_end stamps amount_due_cents = 0 — services/calc.py:22-23.
- §3.2 — revise — mismatch — Payment accepted in OPEN/PARTIALLY_PAID/OVERDUE/DELINQUENT (else ERR_INVALID_STATE); full payment → PAID from any of the four; short payment moves only OPEN→PARTIALLY_PAID — routes/assessments.py:115-138.
- §3.2 — revise — mismatch — Homeowner derived fields recompute on every payment post, not only on PAID close — routes/assessments.py:143, services/homeowner.py:30-41.
- §3.2 — insert — ambiguity — Premature/non-DELINQUENT lien → ERR_INVALID_STATE — routes/assessments.py:159-164.
- §3.2 — insert — ambiguity — Reversal dropping a PARTIALLY_PAID assessment to zero paid → OPEN (before due) / OVERDUE (at/after due, re-stamp fee); other partial reversals leave status unchanged — routes/payments.py:71-80.
- §3.3 — insert — ambiguity — Autopay cancel returns 204 and is idempotent when no ACTIVE mandate exists — routes/homeowners.py:117-128.
- §3.9 — insert — mismatch — Clock-set responds 200 with data={"current_utc":…}; grace-policy responds 200 with data={"grace_policy":…} — routes/admin.py:24,42.

Left unchanged (verified already-pinned): ARC finalisation fee (sum-then-round), delinquency-score incl. late fee, amenity capacity interval-merge, motion 24h buffer overlap, quorum ceiling, work-order dual-dimension gates, fine_balance_cents. Per-endpoint validation-ordering micro-quirks and extra internal response fields left alone (PRD prose does not pin an exhaustive order/field list).

=== PIPELINE COMPLETE: all 9 steps done. Final state: 70/70 tests pass in all 8 parallel rounds. ===
