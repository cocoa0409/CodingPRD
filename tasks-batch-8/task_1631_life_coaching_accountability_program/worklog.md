# Worklog — task_1631_life_coaching_accountability_program

## Step 1: Create task directory — 2026-08-14T03:31:00.000Z

Task directory `tasks/task_1631_life_coaching_accountability_program/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; treated as DONE per instructions (no index scan, no writes outside this directory).

## Step 2: Generate scaffold — 2026-08-14T04:34:00.000Z

## Scaffold generation complete — task_1631_life_coaching_accountability_program

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1631_life_coaching_accountability_program/`):
- `SCAFFOLD.yaml` (1645 lines) — §1.0–§1.7, no difficulty/corner keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1954 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (2927 lines) — single key `scaffold_corner_design`

**Surface counts:**
- **14 entities**: Coach, Client, ProgramTier, DiscoveryCall, FitAssessment, Enrollment, Installment, Session, Goal, HabitCheckIn, Cohort, CohortMembership, Testimonial, RefundRequest
- **9 state machines** (all 14 entities minus Installment/HabitCheckIn/FitAssessment which are append-only `common_fields: false`): Enrollment has parallel dims (lifecycle × payment_status, both cyclic); Session and Testimonial cyclic; DiscoveryCall has a NO_SHOW→SCHEDULED loop; Cohort branching
- **6 calculations**: refund_amount (dual-variant COOLING_OFF/PRO_RATA, day-14 `<=` boundary), client_engagement_score (weighted scoring, provisional vs final denominators), installment_schedule (floor + remainder-to-LAST), pro_rata_session_value (tiered branch: SINGLE→0 / PACKAGE flat / MEMBERSHIP time-prorated double-floor), reschedule_policy_gate (strict `<` 24h), habit_streak_freeze (chronological)
- **20 validations** (priorities 1–20, unique), **67 endpoints** (incl. `/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default and `/_payments/simulate`), **20 errors**, **4 roles** (PlatformAdmin/PracticeManager opaque; Coach/Client entity-backed; segregation of duties on fit assessment and credential verification)
- **2 OCC concurrency rules** on Enrollment (pause, cancel)

**§1.8: 18 difficulty instances** (2 per rule, all with full replayable chains):
- Dual-variant calcs on different domains (RefundRequest fiscal vs Client engagement)
- Combinatorial formulas in different modes — (a) tiered branch and (b) pinned rounding order
- Non-linear machines on different entities (Enrollment parallel dims; Testimonial consent cycle)
- Transitive cascades depth-3 (coach ethics suspension) and depth-2 (refund approval with waitlist promotion)
- Priority conflicts on different category pairs (state vs business_temporal; business_safety vs business_fiscal)
- Boundaries on different metrics/endpoints (86400s free-window; cohort capacity `==` → WAITLISTED)
- Cross-entity gates on different pairs (Session→Coach credential; Session→Enrollment lifecycle)
- Overlap rules with different interval semantics (sessions: half-open + 15m buffer; discovery calls: closed, no buffer — same adjacency gives opposite verdicts)
- Compensating invariants on different conserved quantities (session credits; installment schedule money total)

**§1.9: 48 corner instances** (43 active + 5 `excluded_because` stubs pointing at §1.8), spanning entities / state machines / calculations / validations / endpoints / errors / RBAC / cross-cutting / consistency sections.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (67 endpoints, 14 entities, 18 §1.8 + 43 §1.9 active instances, 985 calls scanned.)

**Notable design decisions:**
- Reschedule is modeled as old-session-CANCELLED-with-`successor_session_id` → new SCHEDULED session, making the cycle explicit and observable
- All formula-derived assert literals were pre-computed with Python (e.g., refund 65000 vs 55000 across the day-14/15 boundary; MEMBERSHIP refund 54994 exposing the double-floor; installment vector [26666, 26666, 26668]; engagement 9 and 1)
- refund PRO_RATA delegates its gross to `pro_rata_session_value` so the tiered-branch calc is observable through the refund endpoint
- `sessions_remaining` pins `total − consumed − SCHEDULED − FORFEITED` (cancel returns credits, forfeit burns them)
- Logical clock + payment simulator are the only test-driving endpoints; everything else is business surface. No sibling task directories were inspected.

## Step 3: Copy shared files — 2026-08-14T04:35:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1631_life_coaching_accountability_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T04:55:00.000Z

All contracts pass. PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1631_life_coaching_accountability_program/workspace/PRD.md` — 325 lines. (The `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` files were never opened or referenced.)

## Section list
- **§1 Introduction** (2 paragraphs + mount note)
- **§2** with 11 subsections: 2.1 RBAC, 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 The Logical Clock, 2.6 Money/Counts/Rounding, 2.7 Credentialing/Ethics/Segregation of Duties, 2.8 OCC, 2.9 Two Interval Regimes for Scheduling Conflicts, 2.10 Cascades/Derived-Field Reconciliation, 2.11 Validation Order
- **§3** with 9 subsections: roster/registry → discovery/fit gate → enrollment/payments/activation → sessions → pause/resume/cancel → goals/habits/engagement → cohorts → testimonials/consent → refunds
- **§4** endpoint table (67 rows, 4 columns), **§5** error catalogue (20 rows, 2 columns)

## Scaffold coverage
All 14 entities, all 9 state machines (incl. parallel credential/ethics and lifecycle/payment dimensions, the NO_SHOW→SCHEDULED discovery cycle, reschedule successor cycle, consent re-cycle), all 6 calculations (refund_amount, engagement score final+provisional, installment_schedule, pro_rata_session_value, reschedule gate, habit streak), all 20 validations with priority ordering, both OCC rules, all 67 endpoints, all 20 errors, all 4 roles with identity translations.

## Hard Contract Reports
```
Field coverage check:
- entities[].fields: 71 required, 71 present, 0 missing
- endpoints[].request_body/input: 50 required, 50 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
Status: PASS (two passes; first pass caught installment_status, repaired in §3.3)

Rule coverage check:
- validations[] with priority: 20 checked, 20 expressed in ordered §2.11 prose, 0 missing
- concurrency_rules[] OCC rejections: 2 scaffold rules + resume (declared by its endpoint input list and transition precondition), all with write action + expected_enrollment_version + ERR_STALE_VERSION/412, 0 missing
- state_machines[].transitions: 36 checked, 36 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed in precise prose, 0 missing
- validations[] conditions: 20 checked, 20 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all checked and expressed (incl. all five ERR_DUPLICATE_RESOURCE scopes, both coach-capacity enforcement points, all four credential-gated operations)
- entities[].fields[] structured content: initials, defaults, nullability (cohort_id, successor_session_id), ranges all reconstructible
- sibling-branch symmetry: SINGLE/PACKAGE/MEMBERSHIP refund branches, three discovery resolutions, consent/publish dimensions — equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 424
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Zero-Silence decisions (stated explicitly rather than left to inference)
- **Resume OCC**: scaffold's `concurrency_rules` lists only pause/cancel, but the resume endpoint's input list and its transition precondition both declare `expected_enrollment_version` — I covered all three (superset of the OCC table, faithful to endpoints + state machine).
- Stated explicitly: `DEFAULTED` has no outbound payment-dimension path; `DECLINED` consent has no onward transitions; session `NO_SHOW` is terminal (contrast with discovery-call `NO_SHOW`); credential `EXPIRED` gates completion without a defined re-verification transition (rendered as "cannot be completed while not VERIFIED", no invented transition); enrollment auto-`COMPLETED` does not auto-achieve goals but does remove `ACTIVE` memberships; cohort completion removes only `WAITLISTED` memberships; boundary inclusivity for day-14 cooling-off, exactly-24h-free reschedule, `achieved_count` reaching `target_count`, booking at exactly one remaining credit.
- **pro_rata FORFEITED gloss**: the scaffold's `input_set` note ("excludes FORFEITED from 'remaining'") tensions with its own formula (`session_count − sessions_consumed`); I rendered the formula exactly and omitted the contradicting gloss, since the formula is the normative statement.

## Deliberate scattering / implicit-information choices
- **Unit conversion of constants**: `PER_SESSION_COOLING_OFF_CENTS: 7500` → "a flat $75.00 fee"; `ADMIN_FEE_CENTS: 5000` → "$50.00" (§3.9); day/hour constants rendered in words ("twenty-eight-day window", "fourteen consecutive days", "fifteen-minute buffer").
- **OCC** defined mechanically in §2.8, re-narrated with triggers in §3.5; **overlap regimes** defined in §2.9, referenced but not restated in §3.2/§3.4.
- **Engagement-score recompute triggers** split across §3.4 (session terminal transitions) and §3.6 (check-ins + full formula).
- **Filter query params** scattered into per-resource subsections (`credential_status`, `tier_status`, `score_variant`, `member_status`, `successor_session_id`, etc.); foreign keys introduced through action narrative ("naming `client_id`, `coach_id`, …") rather than schema declarations.
- §4 holds only Method/Path/Description/Roles; §5 holds only Error ID/HTTP Status — all trigger conditions live in §2/§3 prose.

## Step 5: Generate unit tests — 2026-08-14T05:20:00.000Z

## Files created

**test_helpers/** (Stage 1 — 9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1631_life_coaching_accountability_program/test_helpers/`):
- `types.py` — 12 entity TypedDicts; append-only entities (FitAssessment, Installment, HabitCheckIn, CohortMembership) omit `updated_at`/`version` per PRD §2.4; all status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (71 methods)
- `api_errors.py` — all 20 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_session_credit_invariant`; append-only assertions enforce absence of `updated_at`/`version`
- `factories.py`, `constants.py` (COOLING_OFF_DAYS=14, 7500/5000-cent fees, RESCHEDULE_FREE_HOURS=24, BUFFER_MINUTES=15, PAUSE_LIMIT=2, etc.), `test_users.py` (opaque PlatformAdmin/PracticeManager constants + mandatory `make_coach_headers`/`make_client_headers` for the two entity-backed roles)
- `fixtures.py` — composite builders: `setup_coach_pair`, `complete_discovery_call_with_fit`, `create_fit_approved_enrollment`, `activate_enrollment`, `setup_active_enrollment`, `setup_multi_client_active_enrollments`, `create_open_cohort`, `add_member`, OCC-correct `pause_enrollment`/`resume_enrollment`, `complete_sessions_for_enrollment`
- `__init__.py` barrel

**test_suite/** (Stage 2 — `conftest.py` + 10 test files):
- `test_01_master_data.py` (6), `test_02_discovery_and_fit.py` (4), `test_03_enrollment_payments.py` (8), `test_04_sessions.py` (13), `test_05_enrollment_lifecycle.py` (5), `test_06_goals_engagement.py` (8), `test_07_cohorts.py` (5), `test_08_refunds_and_consent.py` (12), `test_09_credentialing_and_precedence.py` (6), `test_10_access_and_listings.py` (7)

## Totals
- **79 tests** emitted; pytest collects all 79; everything byte-compiles.
- **Queue A: 36 tests** — all 18 difficulty instances × exactly 2 tests each.
- **Queue B: 43 tests** — all 43 non-stub corner instances × 1 test each (entities 6, state_machines 6, calculations 2, validations 14, endpoints 3, errors 1, rbac 3, cross_cutting_layers 3, consistency_model 4 — totals 42 + error_envelope = 43).

## Skipped instances
None. All 18 §1.8 instances and all 43 non-stub §1.9 instances passed the PRD-first two-condition filter and were translated. The 5 `excluded_because` stubs (refund_cooling_off_boundary_day14_vs_day15, err_session_overlap_triggerable, err_discovery_call_overlap_triggerable, err_coach_not_credentialed_triggerable, err_fit_not_established_triggerable) were correctly not translated; all five difficulty-instance cross-references resolve to real §1.8 instances that carry the assertion.

## Coverage-audit verdict
Machine-checked: queue A — 18/18 non-stub instances at ≥2 tests, zero phantom tags; queue B — 43/43 non-stub instances at ≥1 test, zero phantom tags. Every docstring carries a verbatim PRD quote (whitespace-normalized grep-verified against `workspace/PRD.md`, no ellipses) and ends with exactly one `Design:` tag resolving to a real instance. No `skip`/`xfail` markers anywhere.

Key numeric pins translated verbatim from the indices: COOLING_OFF day-14 = 65000 vs PRO_RATA day-15 = 55000; MEMBERSHIP double-floor 54994; installment split [26666, 26666, 26668] with due dates 2026-08-03/09-02/10-02; engagement provisional 100 vs final 25; filter-case score 9; partial-pay PRO_RATA 21666 (paid 26666 − refunded 21666 = 5000 admin fee); 24h/86399s reschedule boundary; capacity-2 cohort ACTIVE/ACTIVE/WAITLISTED.

## Step 6: Generate implementation — 2026-08-14T05:20:00.000Z

Implementation complete and verified. Final summary:

## File list — `tasks/task_1631_life_coaching_accountability_program/workspace/implementation/`

| File | Role |
|---|---|
| `start.sh` | Guarded launcher: `pip install` only if flask import fails; `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000), foreground |
| `requirements.txt` | `flask>=2.2` |
| `app.py` | Flask entry point, blueprint registration, envelope-shaped 404/405/exception handlers |
| `db.py` | In-memory store (14 dicts keyed by id) + logical clock, booting empty at exactly `2026-08-01T00:00:00Z` |
| `errors.py` | All 20 catalog error IDs with exact HTTP statuses |
| `envelope.py` | `meta`/`response_type`/`data` envelope, `req_` request ids, 3-fractional-digit timestamps, `limit`/`offset`/`total_count`/`has_more` pagination (default 10, clamp 1..100) |
| `auth.py` | `X-User-ID`/`X-User-Role` extraction; 401 for missing/unknown role or missing id for entity-backed roles; 403 for role mismatch, nonexistent entity-backed caller, and ownership failures |
| `timeutil.py` | Logical-clock reads, ISO 8601 parse/format (millis + `Z`) |
| `calc.py` | §1.3 calculations: `installment_schedule` (floor split, remainder on LAST), `refund_amount` (COOLING_OFF ≤ day 14 / PRO_RATA ≥ 15), `pro_rata_session_value` (SINGLE/PACKAGE/MEMBERSHIP tiers, pinned price basis), `client_engagement_score` (final + provisional windows, exact round-half-up via `Fraction`, clamp 0..100), reschedule gate (strictly < 24 h), constants |
| `serializers.py` | Field-exact serializers; `version` starts at 1; append-style records (FitAssessment, Installment, HabitCheckIn, CohortMembership) carry only `id`/`created_at`; derived fields (`sessions_consumed`, `sessions_remaining`, `paid_cents`, `refunded_cents`, `achieved_count`, `engagement_score`) computed at read time |
| `engine.py` | Cascades (coach revoke/suspend, enrollment pause/cancel/refund, cohort cancel, completion bubble-up), waitlist promotion (joined_at → created_at → insertion order), both interval regimes (sessions: half-open + 15-min buffer; discovery calls: closed, no buffer), and the clock-set sweep (credential expiry, delinquency → 14-day default, cohort window progression, session forfeiture) |
| `routes/infra.py` | `_clock/set_current_utc`, `_payments/simulate` (activation with credential + capacity gates, delinquency settle, FAILED no-op) |
| `routes/coaches.py`, `clients.py`, `tiers.py`, `discovery.py`, `enrollments.py`, `sessions.py`, `goals.py`, `cohorts.py`, `testimonials.py`, `refunds.py` | Resource groups |

**PRD section → module mapping:** §2.1 auth → `auth.py`; §2.2/§2.3 envelope+pagination → `envelope.py`; §2.4 fields/versioning → `serializers.py`; §2.5 clock → `db.py` + `engine.sweep`; §2.7 credentialing/SoD → `routes/coaches.py`, `routes/discovery.py`; §2.8 OCC → `routes/enrollments.py` (`expected_enrollment_version`, 412); §2.9 intervals → `engine.py`; §2.11 precedence → per-route ordered checks (auth → forbidden → existence → state → OCC → credential → fit → overlaps → window → cap → credits → capacity → joinable → uniqueness → SoD → tier → plan → refund → shape); §3.1–§3.9 workflows → the matching route modules.

**Endpoint count: 67/67** implemented per the §1.5/§4 tables.

**Verification:** two ad-hoc suites I wrote against the PRD's concrete numbers — 137/137 and 42/42 checks pass on fresh boots, covering envelope shape, auth/RBAC, both overlap regimes (touching collides for calls, not for sessions), installment waterfall (100001¢/3 → 33333/33333/33335), activation gates, reschedule 24 h boundary (exactly 24 h = free), cap enforcement, engagement final vs provisional (8 vs 60), COOLING_OFF day-14 boundary, PRO_RATA PACKAGE/MEMBERSHIP/SINGLE math, delinquency → 14-day default, pause-limit/OCC precedence, bubble-up completion, waitlist promotion on delete and on enrollment cancel, revoke/suspend cascades, forfeiture, consent/publish cycle, tier retirement, and reboot-wipe (state empty + clock reset after kill/restart via `start.sh`).

**Ambiguities resolved (PRD-silent points):**
1. **Reschedule response body** — returns the *newly created* session (exposes `is_late_reschedule`); old session's `successor_session_id` is readable via GET.
2. **Free reschedule version bump** — enrollment `version` bumps only on *late* reschedules (PRD §3.4 mentions the bump only in the counted branch); derived-count recomputes alone never bump.
3. **Payments on terminal enrollments** — the payment dimension is parallel with no lifecycle preconditions, so SUCCEEDED pays next PENDING / settles LATE on COMPLETED/CANCELLED/REFUNDED enrollments; only DEFAULTED rejects (409, "no path out").
4. **DEFAULTED blocking errors** — booking/completion under DEFAULTED → `ERR_INVALID_STATE` (409, state category).
5. **Delinquency fuse measurement** — defaulted when `(today − earliest overdue due_on).days >= 14`; a single large clock jump can fire CURRENT→DELINQUENT→DEFAULTED in one sweep.
6. **Engagement recompute timing** — computed at read against the logical clock rather than stored, satisfying every declared trigger and staying correct across clock sets.
7. **`due_on` pre-activation** — serialized as `null` until activation ("resolves only at activation").
8. **Tier code uniqueness** — not enforced (the §1.4 uniqueness rule enumerates emails, fit assessments, testimonials, check-ins only).
9. **Initial `version`** — 1 at creation, +1 per mutation including cascade-reached rows.

## Step 7: Run tests and iterate — 2026-08-14T05:45:00.000Z

Clean 8-round sweep achieved: **79/79 passed in every round**.

## Summary

- **Iterations run:** 2 sweeps (sweep 1: 72/79 per round, 7 tests failing deterministically in all 8 rounds; sweep 2 was killed mid-flight to fold in an additional correctness fix to one of the already-edited tests; sweep 3: 8×79/79, ALL_CLEAN).

- **Tests deleted:** none. Every failure traced to PRD-covered rules; all fixes were corrections toward PRD fidelity.

- **Fixes applied to `test_helpers/`:** none — the shared fixtures/factories/header builders were all PRD-consistent (the triage-hint check: the ≥5-same-setup-error pattern here was three tests passing `capacity=1` inline, not a helper bug).

- **Fixes applied to `implementation/`:** none. The implementation was PRD-faithful in all 7 failures.

- **Fixes applied to `test_suite/`** (all STEP 2 test bugs):
  1. `test_02_discovery_and_fit.py::test_discovery_call_no_show_cycle_back_to_scheduled` — asserted exact-string echo of `scheduled_start` (`"…10:00:00Z"` vs the server's normalized `…10:00:00.000Z`). PRD §3.2 covers only "the new start recorded"; §2.4's three-fractional-digit format applies to system `created_at`/`updated_at`, not client-supplied instants. Replaced with instant-equality comparison (`datetime.fromisoformat`), keeping all covered assertions (NO_SHOW → SCHEDULED → COMPLETED cycle).
  2. `test_06_goals_engagement.py::test_engagement_score_provisional_variant_at_day_seven` → renamed `..._mid_window` — expected 100 via an internally inconsistent hybrid (denominators for 7 days, count window of 8 dates). PRD §3.6: "its length is the number of days from the anchor through today inclusive" → 8 for anchor 2026-08-03 → today 2026-08-10; denominators floor(8·8/28)=2 and 8 → uniquely derives 95. Fixed assertion to 95 with the corrected derivation; updated scenario docstring.
  3. `test_08_refunds_and_consent.py::test_pro_rata_refund_membership_branch_double_floor` — expected 54994 via date arithmetic (days_left=42). PRD §3.9 defines days_left as "the window's closing instant minus the current time": at 2026-09-14T09:00Z, close 2026-10-26T00:00Z − now = 41d15h → 41 whole days → 53563 (the explicit instant/time wording contrasts with the date-based days_elapsed sentence two paragraphs up, making this uniquely derivable). Fixed assertion to 53563 with the instant-arithmetic derivation.
  4. `test_07_cohorts.py::test_waitlist_promotion_order_by_joined_at` — setup used `capacity=1`; PRD §3.7/§2.11 require "a `capacity` of at least 2" (implementation's 400 was correct). Rebuilt with capacity=2 and 4 enrollments (2 ACTIVE + 2 WAITLISTED so promotion order is observable), and staggered the logical clock between the two waitlisted joins so "the earliest `joined_at` wins" decides the order without leaning on the created_at tie-break (which would have been tied at one logical instant — a unique-derivability gap in the original design).
  5. `test_07_cohorts.py::test_cohort_date_progression_open_to_completed` — same capacity=1 violation; rebuilt with capacity=2 and 3 enrollments (one WAITLISTED member to exercise the completion cascade).
  6. `test_08_refunds_and_consent.py::_setup_refund_cascade_scenario` (shared by `test_refund_approval_refunds_enrollment_and_cancels_sessions` and `test_refund_approval_removes_membership_and_promotes_waitlist`) — same capacity=1 violation; rebuilt with capacity=2 and 3 enrollments (R ACTIVE, X ACTIVE filler, W WAITLISTED), preserving both tests' original assertions (RR amount 80000 COOLING_OFF; memb_r REMOVED; memb_w promoted ACTIVE).

- **Doc-generator feedback (unique-derivability / silence notes, no deletions needed):** (a) §3.6's "the number of elapsed days" invited a denominator reading (today−anchor=7) inconsistent with its own inclusive length definition — the design index's hand-pin (100 at "day 7") baked that misreading in; (b) §3.9's instant-vs-date contrast was lost on the design index, which pinned days_left=42 at a 09:00 clock where instant arithmetic yields 41; (c) the corner-design recipes for waitlist promotion assumed capacity=1 cohorts, contradicting the §2.11 capacity≥2 floor that the same scaffold declares.

## Step 8: Finalize PRD — 2026-08-14T05:55:00.000Z

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1631_life_coaching_accountability_program/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 324 lines; PRD_FINALIZED.md = 326 lines; delta = +2 lines (+0.62%). Three edits total, all inline (no new sections).

**Changes:**
- **§2.4** — insert — new paragraph pinning that every instant the API returns (server-stamped `activated_at`/`joined_at`, the clock's `current_utc`, and client-supplied `scheduled_start` on sessions/discovery calls) is rendered in the canonical ISO 8601 UTC form with exactly three fractional digits and `Z`, and that client-supplied instants are converted to UTC at intake and read back canonically (`…T10:00:00Z` → `…T10:00:00.000Z`) — `implementation/timeutil.py:18-23,34-49`, `serializers.py:110,140,172`, `routes/infra.py:32`, `routes/cohorts.py:148`.
- **§3.6** — revise — provisional-score denominators now defined off the already-defined inclusive window length ("eight multiplied by the window's length, divided by twenty-eight, rounded down…never less than one"; "the habit denominator becomes that same length in days…includes both the anchor day and today"), replacing the ambiguous "elapsed days"/"elapsed fraction" phrasing — `implementation/calc.py:153,159-160`.
- **§3.9** — revise — MEMBERSHIP pro-rata `days_left` clarified as "the span from the current time to the window's closing instant, taken as an instant-to-instant duration and counted in whole days only, with any partial remaining day discarded and the count never below zero" — `implementation/calc.py:96-99`.

**Step-7 items with no PRD edit (pure fixture bugs; PRD already determines behavior):** the three `capacity=1` cohort setups (items 4, 5, 6) — §2.11/§3.7 already pin `capacity ≥ 2` and impl enforces it (`routes/cohorts.py:36`); the `joined_at`→`created_at` promotion tie-break is already pinned in §3.7 and matches `engine.py:40`, so the clock-staggering test redesign required no PRD change. Doc-generator feedback (c) similarly required no edit.

**Per-edit pre-edit search log:**

1. **§2.4 canonical-instant edit.** (a) Subject: representation of instants served/accepted by the API. (b) Enumerated paths: intake — `timeutil.parse_datetime` (naive→UTC, offset→converted) called at `routes/discovery.py:35,132`, `routes/sessions.py:65,220`, `routes/infra.py:26`; render — `timeutil.fmt_dt` called at `serializers.py:110` (discovery `scheduled_start`), `:140` (`activated_at`), `:172` (session `scheduled_start`), `routes/infra.py:32` (`current_utc`); `now_iso()` (wraps `fmt_dt`) feeds `created_at`/`updated_at` (`serializers.py:20-40`), `joined_at` (`routes/cohorts.py:148`), and envelope `api_request_timestamp` (`envelope.py:20`, already pinned canonical by §2.2's example). Date fields (`credential_expires_on`, `due_on`, `check_in_date`, `window_start/end`) use `parse_date`/`fmt_date` and were deliberately excluded by saying "instant", not "date". (c) Wording adjustment: scoped to instants only, and stated "accepted in ISO 8601 and converted to UTC" without pinning rejection semantics for naive/offset inputs (impl leniency left under-determined).

2. **§3.6 provisional-denominator edit.** (a) Subject: provisional engagement-score window denominators. (b) Enumerated paths: `calc.engagement_score` (`calc.py:138-179`, both variants), its sole caller `serializers.client` (`serializers.py:73-86`), and its endpoint `routes/clients.py:44-46` (single-fetch only, matching the PRD's "Fetching a single client" framing, which I left untouched). Verified against test expectation 95 for anchor 2026-08-03 → today 2026-08-10 (L=8: session denom `max(1, 64//28)=2`, habit denom 8). The final-variant sentence and anchor/tie-break sentence were left verbatim; impl's unflagged behaviors (no-activated-enrollment fallback L=28, future-anchor clamp to 1) were not pinned, per hard scope. (c) Wording adjustment: replaced "elapsed" with explicit reference to the window "length" defined one sentence earlier; no other sentence needed changes.

3. **§3.9 MEMBERSHIP days-left edit.** (a) Subject: whole-days-left factor in the MEMBERSHIP pro-rata branch. (b) Enumerated paths: `calc.pro_rata_session_value` (`calc.py:96-100`) is the only `days_left` consumer; PACKAGE/SINGLE branches don't use it. The date-based `days_elapsed` sentence (`calc.py:109`, COOLING_OFF selection) was deliberately left untouched, preserving the intended instant-vs-date contrast. Window-close instant semantics (`activated_at + duration_days`) cross-checked against §3.3's window definition, `_inside_program_window` (`routes/sessions.py:40-41`), and session forfeiture (`engine.py:204-207`) — all instant-based, consistent with "closing instant". Verified derivation 41d15h → 41 → 53563. (c) Wording adjustment: rephrased the subtraction as a span ("from the current time to the window's closing instant…counted in whole days only, partial day discarded") to kill the date-arithmetic misreading while keeping the original "never below zero" clause.

## Step 9: Complete PRD — 2026-08-14T06:15:00.000Z

The diff is exactly the 20 intended edits. All work is complete.

## Summary

**Files:** `/home/ubuntu/github/CodingPRD/tasks/task_1631_life_coaching_accountability_program/workspace/PRD_FINALIZED.md` (326 lines / 49,910 chars) → `/home/ubuntu/github/CodingPRD/tasks/task_1631_life_coaching_accountability_program/workspace/PRD_COMPLETED.md` (328 lines / 53,606 chars). Char-delta **+3,696**, line-delta **+2** (one inserted paragraph in §2.1 plus its blank separator; all other edits are inline in-paragraph inserts/revisions).

**Counts:** 23 changes total — **22 ambiguity-pins, 1 mismatch-revision**.

**Changes (one per bullet):**

- §2.1 — insert — ambiguity — read endpoints (GET) enforce role membership only, never ownership; sole exception is the coach fit-assessment listing restricted to the path coach's own graded assessments — implementation/routes/clients.py:37-57, implementation/routes/coaches.py:142-155
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamp to bounds; non-integer values fall back to defaults (no error) — implementation/envelope.py:60-72
- §2.3 — revise — ambiguity — list ordering ties on identical creation timestamps break by creation sequence, earliest first — implementation/serializers.py:29 (`_created_sort`), all list routes
- §2.4 — revise — ambiguity — `version` begins at 1 at creation; `updated_at` initially equals `created_at` — implementation/serializers.py:20-30
- §2.5 — insert — ambiguity — the supplied clock instant is accepted verbatim (forward or back); one set fires chained transitions in a single evaluation (OPEN→IN_PROGRESS→COMPLETED, DELINQUENT→DEFAULTED in the same set) — implementation/routes/infra.py:21-32, implementation/engine.py:135-207
- §2.8 — insert — ambiguity — missing/non-integer `expected_enrollment_version` → `ERR_INVALID_REQUEST` (400) raised at the OCC step, ahead of business rules — implementation/routes/enrollments.py:32-41
- §2.11 — insert — ambiguity — absent/malformed JSON body treated as an empty object, surfacing as missing-field 400s — implementation/auth.py:46-49
- §3.1 — insert — ambiguity — verifying a non-`PENDING_VERIFICATION` coach or one whose `credential_expires_on` is not strictly future → `ERR_INVALID_STATE` (409) — implementation/routes/coaches.py:83-88
- §3.1 — insert — ambiguity — revoking a credential not `VERIFIED` → `ERR_INVALID_STATE` (409) — implementation/routes/coaches.py:104-106
- §3.1 — revise — ambiguity — suspending an ethics posture not `ACTIVE` → `ERR_INVALID_STATE` (409) — implementation/routes/coaches.py:122-124
- §3.3 — insert — ambiguity — enrollment creation does not cross-check the discovery call's own client/coach against the named `client_id`/`coach_id` (existence + fit gate only) — implementation/routes/enrollments.py:44-121
- §3.3 — revise — ambiguity — default fuse measured from the earliest still-`LATE` installment's `due_on` (defaults at ≥14 days past it); simulated successful payment on `DEFAULTED` → `ERR_INVALID_STATE` (409); `DEFAULTED` blocks booking/completion with `ERR_INVALID_STATE` (409) — implementation/engine.py:170-179, implementation/routes/infra.py:89-91, implementation/routes/sessions.py:62-64,147-149
- §3.4 — revise — ambiguity — a supplied booking `cohort_id` is validated for existence only (no joinability/ownership check) — implementation/routes/sessions.py:54-57
- §3.4 — insert — ambiguity — a no-show that brings consumption to `sessions_total` bubbles the enrollment to `COMPLETED` with the same membership cascade as completion — implementation/routes/sessions.py:179-183, implementation/engine.py:120-130
- §3.4 — revise — ambiguity — reschedule conflict check excludes the session being moved; the successor inherits the moved session's `cohort_id`; the response carries the newly created session — implementation/routes/sessions.py:224-262
- §3.6 — revise — ambiguity — goal creation has no enrollment-lifecycle precondition — implementation/routes/goals.py:34-57
- §3.6 — insert — ambiguity — `check_in_date` is unconstrained relative to the current date (past and future dates file alike) — implementation/routes/goals.py:106-115
- §3.6 — revise — ambiguity — provisional window length never shorter than one day; a client with no activated enrollment scores the provisional variant over the full 28-day window, identical to final — implementation/calc.py:146-165
- §3.7 — revise — ambiguity — `window_start`/`window_end` are not cross-validated; inverted windows accepted — implementation/routes/cohorts.py:34-39
- §3.7 — revise — ambiguity — waitlist-promotion ties surviving both `joined_at` and `created_at` break in creation order, earliest first — implementation/engine.py:40
- §3.8 — insert — ambiguity — testimonial filing carries no enrollment-lifecycle precondition; the lifecycle gate applies only at publication — implementation/routes/testimonials.py:31-59
- §3.9 — insert — ambiguity — the `COOLING_OFF` figure is not floored at zero (heavy consumption can drive `amount_cents` negative), unlike pro-rata — implementation/calc.py:112-114
- §3.9 — revise — **mismatch** — refund approval moves only the enrollment's `ACTIVE` cohort memberships to `REMOVED`; a `WAITLISTED` membership of the enrollment is left in place (PRD previously said unqualified "its cohort memberships") — implementation/engine.py:52-58

Everything else in the implementation (envelope shape, error catalog, RBAC table, state machines, installment waterfall, refund pro-rata formulas, engagement-score math, OCC set, overlap arithmetic, cascades, filters, sort orders, 201/200 status mapping) was already uniquely pinned by PRD_FINALIZED.md and verified against the code with no change needed.
