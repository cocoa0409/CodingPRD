# Worklog — task_0777_online_course_creator

Scenario: Online-Course Creator Platform (Teachable/Kajabi style): creator & course builder/curriculum, pricing (one-time/subscription/payment-plan) & coupon, student enrollment & drip/progress, community/membership & email, affiliate & revenue/payout, quiz/certificate, refund window, analytics
Difficulty: Expert

## Step 1: Create Task Directory — 2026-07-06T17:19:00.000Z

Task directory tasks/task_0777_online_course_creator pre-created by orchestration args; skipped directory scan / index computation per instructions. Created workspace/ subdirectory.

## Step 2: Generate Scaffold — 2026-07-06T17:45:00.000Z

All three files generated, parse cleanly, pass scaffold linter (VERDICT: clean lint). Expert difficulty.

Complexity profile: primary pricing_engine + secondary ledger_reconciliation; flat topology; parallel/cyclic state shapes; peer-role RBAC; layers = dual-variant calc, cascading side effects, rate/threshold triggers, optimistic concurrency.

Entities (11): Creator, Student, Course, Lesson, PricePlan, Coupon, Affiliate, Enrollment, Invoice, Payout, QuizAttempt. Certificate/community/email modeled as computed fields on Enrollment/Course.

State machines (5): Course (cyclic publish→unpublish→republish→archive), Enrollment (two parallel axes: access_status × billing_status), Invoice (branching pay/refund/void), Payout (linear + cancel/fail).

Calculations (10): checkout_charge (tiered, plan-type × coupon-type branching), installment_split (ceil-then-remainder), platform_fee, affiliate_commission (per-invoice-then-sum), creator_net, course_revenue (dual variant gross vs net-settled), enrollment_completion (dual variant raw progress vs mastery), enrollment_billing_total, creator_available_balance, creator_net_ledger_invariant. Constants: PLATFORM_FEE_PCT=10; logical-clock default 2026-03-01T00:00:00Z.

Endpoints (41), Errors (42), Roles (3): PlatformAdmin (opaque), Creator (entity_backed), Student (entity_backed). One /_clock/set_current_utc test-driving endpoint. One concurrency rule: OCC on Creator.version guarding POST /creators/{id}/payouts.

§1.8: 18 instances (2 per each of 9 rules), numeric asserts precomputed to literals. §1.9: 29 active instances + excluded_because stubs.

File sizes: SCAFFOLD.yaml 1160 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1096 lines, SCAFFOLD_CORNER_DESIGN.yaml 1343 lines.

## Step 3: Copy Shared Files — 2026-07-06T17:45:30.000Z

Copied INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-06T18:00:00.000Z

Generated workspace/PRD.md (289 lines). 5 top-level sections, 18 subsections.
§1 Introduction; §2 Global Specifications (10 subsections: RBAC + validation precedence, verbatim §2.2 envelope, pagination, common properties/versioning, logical clock + time-window semantics, monetary precision, creator earnings ledger, two parallel enrollment axes + cascade consistency, nested-path validation, payout OCC); §3 Business Logic (8 lifecycle subsections); §4 Endpoint table (41 endpoints); §5 Error catalogue (42 errors).

Hard Contracts all PASS: Field-Name Coverage (0 missing), Rule Coverage (12-step precedence, payout OCC, all 5 state machines, all 10 calculations, all cascades), §3 Path Purity (0 URL/HTTP tokens in §3 backticks). All 42 error IDs surface in §2/§3 narrative. §2.2 emitted byte-for-byte. SCAFFOLD_*_DESIGN.yaml not opened.

## Step 5: Generate Unit Tests — 2026-07-06T18:20:00.000Z

test_helpers/ (8 files + barrel) + test_suite/ (conftest + 7 domain files test_01–test_07). 65 tests total, each with exactly one Design: tag. Queue A (Difficulty): 36 tests, all 18 instances ≥2 each. Queue B (Corner): 29 tests, all 29 non-stub instances ≥1 each. 3 excluded_because stubs correctly NOT translated.
Verification: coverage audit PASS (no unknown/dual tags); all 73 quoted PRD citations verbatim in PRD.md; pytest --collect-only gathers 65 tests, 0 import/fixture errors. Skipped instances: none (PRD exhaustive; §2.1 precedence made priority_pair_validation_conflict derivable).

## Step 6: Generate Implementation — 2026-07-06T18:20:30.000Z

workspace/implementation/: start.sh, requirements.txt, store.py, errors.py, serialize.py, app.py. 41 endpoints. In-memory only, empty on every boot (no seeding); logical clock default 2026-03-01T00:00:00Z.
Key decisions: all derived quantities computed live at serialization (ledgers, revenue, redemption counts, progress). Creator.version bumps only on 4 payout events (create, →PAID, →FAILED, →CANCELLED), not invoice pay/refund/set-status → deterministic OCC. Validation precedence per §2.1 (auth→well-formed→role→existence→ownership→state→cross-ref→state-gates→time-window→uniqueness→fiscal→OCC-last). Integer-cent floor math; ceil-with-remainder installment split (3334/3334/3332). Per-invoice commission floors summed. Ambiguity: paying ARCHIVED-course invoice → ERR_INVOICE_NOT_PAYABLE (409); quiz-attempts require enrollment access_status==ACTIVE. Self-verified 73 assertions passing.

## Step 7: Run Tests and Iterate — 2026-07-06T18:45:00.000Z

Iterations run: 2 (initial diagnose sweep, one fix batch, confirming sweep). All 8 rounds pass cleanly (64/64 each). Same 5 tests failed identically every round — no flakiness. Sweep run as 2 waves of 4 to avoid host self-saturation.

Tests deleted (1):
- test_passing_quiz_completes_access_axis (test_suite/test_05_progress_mastery.py) — DELETE under STEP 1b (trigger-timing silence / non-unique derivability). PRD §3.6 verbatim scopes the COMPLETED transition to "When completing a lesson makes mastery newly true, the enrollment's access_status moves ACTIVE → COMPLETED". Test achieves mastery via quiz-pass (lesson completed first, mastery false), asserts access COMPLETED. PRD never states quiz submission fires the transition. Two faithful PRD-only impls both consistent: (A) check mastery only in complete-lesson handler (what impl did) → access stays ACTIVE; (B) re-check on quiz-submit → COMPLETED. Both articulable → PRD does not uniquely determine. Sibling test_billing_axis_unaffected_by_completion kept.

Fixes to test_helpers/ (1):
- test_helpers/fixtures.py → setup_enrollment — 4 affiliate tests failed setup with ERR_AFFILIATE_NOT_FOUND because affiliate created (inside setup_published_course) under default code "AFF" while enrollment attributed test's code ("AF20"/"AF15"). Impl correctly rejected unknown code (real PRD-required check, §3.4). Fixture bug. Fix: when caller supplies affiliate_code AND asks setup to create affiliate (affiliate_pct present), forward affiliate_code into setup_published_course so created affiliate's code matches attribution.

Fixes to implementation/: none — no PRD-required check weakened or added.

## Step 8: Finalize PRD — 2026-07-06T18:55:00.000Z

Produced workspace/PRD_FINALIZED.md. PRD.md 289 lines → PRD_FINALIZED.md 289 lines (~0% line delta; one line expanded in place, +~600 chars).

Changes (1):
- §3.6 (Progress, Quizzes, Mastery, Certification) — insert — pinned that the mastery-driven ACTIVE→COMPLETED transition, certificate minting, and completion_count increment are evaluated ONLY during the complete-lesson operation; a quiz-attempt submission never on its own fires them even when its passing attempt makes mastery newly true. Impl: app.py:827 (complete-lesson) vs app.py:858-885 (quiz-attempt, no mastery re-check). Under-determined wording noting is_mastery_complete is a live-computed field that may read true, to avoid contradicting the serializer path. Affiliate fixture item = pure fixture bug, no PRD edit.

## Step 9: Complete PRD — 2026-07-06T19:05:00.000Z

Produced workspace/PRD_COMPLETED.md. PRD_FINALIZED.md → PRD_COMPLETED.md: 289 → 289 lines (all in-paragraph); 42535 → 44285 chars (+1750). ambiguity-pins: 5, mismatch-revisions: 3.

Changes (8):
- §2.1 (RBAC) — insert — ambiguity — X-User-Role outside the three exact spellings → malformed header → ERR_MISSING_AUTH_HEADER (not ERR_UNAUTHORIZED). app.py:69.
- §2.3 (Pagination) — insert — ambiguity — out-of-range limit/offset clamped to bounds; non-integer → ERR_INVALID_REQUEST; created_at ties broken by ascending creation order. app.py:150-170,175.
- §2.4 (Versioning) — revise — mismatch — removed claim that recomputing derived analytics counts as a mutation advancing version/updated_at; analytics computed live at read, never bump version; Creator version advances only on payout activity. serialize.py:77-143 / store.py:105-114 / app.py:243.
- §2.8 (Cascading consistency) — revise — mismatch — only resources whose persisted state changes are versioned (enrollment statuses, invoice, payout); ledger/revenue/commission are live-computed, not re-versioned. app.py:994-1008,1027-1038.
- §3.1 (Onboarding) — insert — mismatch — creator suspend/reactivate refreshes updated_at but does not advance version. app.py:242-243.
- §3.5 (Subscription cycles) — insert — ambiguity — cycle-invoice endpoint does not gate on plan_type; creates CYCLE invoice for any enrollment at plan amount_cents. app.py:888-925.
- §3.6 (Quizzes) — insert — ambiguity — quiz-attempt submission requires enrollment ACTIVE; other access state → ERR_ENROLLMENT_INVALID_STATE. app.py:875-876.
- §4 (Endpoints, /enrollments) — insert — ambiguity — status list filter matches either access or billing axis. app.py:796.

## Pipeline complete — 2026-07-06T19:05:30.000Z

All 9 steps done. Final sweep: 64/64 tests pass across all 8 rounds. Artifacts: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/ (64 tests), workspace/{PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, INSTRUCTION.md, implementation/}.
