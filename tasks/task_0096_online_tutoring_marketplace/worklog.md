# Worklog — task_0096_online_tutoring_marketplace

## Step 1: Create Task Directory — 2026-06-02T03:08:29.000Z

Created `tasks/task_0096_online_tutoring_marketplace/` with `workspace/` subdirectory (fixed path, no auto-scan/increment per pipeline instructions; reserved to avoid ID collision with 3 sibling pipelines running in parallel).

## Step 2: Generate Scaffold — 2026-06-02T03:37:00.000Z

Generated the full scaffold package for **task_0096_online_tutoring_marketplace** (Wyzant-style online tutoring marketplace), built fresh from the scenario description and the scaffold-generator skill alone — no sibling tasks were read.

**Counts produced:**
- **Entities: 11** — Subject, CommissionPolicy, Tutor, Credential, TutorSubjectTag, ParentAccount, Student, Booking, Session, Settlement, RefundCase
- **Endpoints: 52**
- **Error codes: 29**
- **State machines: 6** — Credential, Tutor, TutorSubjectTag, Booking, Session, RefundCase (RefundCase is cyclic; Session carries parallel delivery×settlement dimensions)
- Plus: 6 calculations, 18 validations, 2 concurrency (OCC) rules, 5 roles
- **§1.8 difficulty design: 18 instances** (9 rules × 2), all grounded and arithmetic pre-computed as literals
- **§1.9 corner design: 28 active instances + 5 excluded-because stubs**

**Verification:** `scaffold_lint.py` returns `VERDICT: clean lint` — all 600 §1.8/§1.9 calls conform to §1.5, and every §1.1 FK has reverse-reachability in §1.5. All grounds/assertion error refs resolve, all excluded_because references exist, instance names unique across both files, no forbidden concurrency vocabulary, design-key file split honored. Financial literals (tiered commission, trial-vs-standard divergence, settlement reversal with clawback, wallet conservation invariant) each computed in code and pinned as literals.

**Deviation flagged:** endpoint count is **52, above the Expert band ceiling of 32** (entities 11, state machines 6, errors 29, calculations 6 all within Expert bands). Subagent trimmed redundant reads but stopped there: every remaining endpoint is load-bearing (a declared state-machine transition or a CRUD/FK-reverse-reachability read the lint and downstream generators require). Reaching 32 would have meant deleting working transitions across the 7 distinct scenario workflows. Orchestrator accepts: difficulty comes from interaction density, not endpoint volume; the 9 hard difficulty rules each have ≥2 differentiated instances.

## Step 3: Copy Shared Files — 2026-06-02T03:39:16.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0096_online_tutoring_marketplace/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-02T03:46:50.000Z

**Written:** `workspace/PRD.md` — 286 lines (~46 KB). Generated purely from SCAFFOLD.yaml + doc-generator skill spec. Neither design YAML read; no sibling task read.

**Major sections:** §1 Introduction; §2 Global Specifications (RBAC 5 roles, verbatim §2.2 envelope, pagination, common props, resource existence/validation, cascades, OCC, monetary/basis-point precision, ledger conservation); §3 Business Logic (3.1–3.11 + 3.9.1: platform config, tutor onboarding/credentials, subject tagging/pricing, parent wallets/students, booking, reschedule/cancel/no-show, delivery/confirmation, settlement/commission tiers, refund negotiation/arbitration, settlement reversal, reliability scoring, deterministic clock); §4 Endpoint Definitions (4-col table, all 54 endpoints); §5 Error Code Catalogue (all 29 errors).

**Hard Contracts:** Contract 1 (Field-Name Coverage) PASS; Contract 2 (Rule Coverage) PASS — 6 state machines, 6 calculations, both OCC rules, validation priority ordering, all 29 error IDs + state/enum values; Contract 3 (§3 Path Purity) PASS — no path tokens or bare HTTP methods in §3. §2.2 byte-identical to source.

## Step 5: Generate Unit Tests — 2026-06-02T04:05:54.000Z

Generated complete test infrastructure at the **task root** (not under workspace/).

**`test_helpers/`** (9 files): `__init__.py`, `types.py` (11 entity TypedDicts + 12 status enums + role enum), `api_client.py`, `api_errors.py` (28-error catalog), `assertions.py` (per-entity + parent-ledger conservation invariant), `factories.py`, `constants.py`, `test_users.py` (opaque shared constants + per-instance make_tutor_headers/make_parent_headers builders), `fixtures.py` (setup_marketplace, consume_trial_slot, book_deliver_confirm, setup_confirmed_standard_session, setup_open_refund_case, setup_countered_refund_case, etc.).

**`test_suite/`** (6 files): conftest.py + 5 domain-named test files.

**Test counts:** 64 tests total, all collect cleanly. Queue A (Difficulty): 36 tests covering all 18 instances (9 rules × 2), each with exactly 2 tests. Queue B (Corner): 28 tests covering all 28 non-stub instances, each 1 test. 5 excluded_because stubs correctly NOT translated (deliver_requires_verified_tutor_cross_entity, refund_case_repropose_loop_increments_round, settlement_reversal_clawback_when_balance_short, tier_commission_at_breakpoint, occ_stale_counter_conflict).

**Skips: 0.** Every design instance passed the PRD-first two-condition filter. Borderline case (student_immutable_after_archive_listed_filtered) translated against only its PRD-grounded facet (archive→ARCHIVED/child_count decrement, PRD §3.4) rather than the non-derivable status-filter assertion.

**Verification:** all docstrings carry exactly one Design: tag resolving verbatim to a real YAML instance; every quoted PRD sentence survives literal grep of PRD.md (2 elision-broken quotes corrected); no unused imports; common_fields entities carry version/updated_at.

## Step 6: Generate Implementation — 2026-06-02T04:05:54.000Z

Generated complete Python + Flask implementation in `workspace/implementation/`.

**Source files:** start.sh (foreground launcher, +x), requirements.txt (Flask==3.0.3), app.py (entry point, error handlers, all 54 routes + /_clock/set deterministic-clock endpoint), db.py (in-memory store + deterministic clock), errors.py (full error catalogue verbatim from PRD §5), response.py (meta/response_type/data envelope), middleware.py (X-User-ID/X-User-Role auth, 5 roles, role+ownership checks), serializers.py, common.py (id/created_at/updated_at/version stamping, round_half_up via Decimal, ISO-8601 parse, validation, pagination), services.py (hold amount, billed minutes, commission tier selection, ledger recompute, reliability scoring).

**Storage:** in-memory only — one plain dict per entity collection keyed by id, monotonic sequence for stable created_at sort. No seeding/preloading/hardcoded data. Money uses integer cents with Decimal/ROUND_HALF_UP.

**start.sh:** app.py reads `int(os.environ.get("PORT","10000"))`, binds 0.0.0.0 foreground via `exec python3 app.py`. pip sentinel-guarded: `if ! python3 -c "import flask"...; then pip install -q -r requirements.txt; fi`.

**Self-verification:** booted ~2s, exercised credential verification w/ tutor bubble-up, credential-gated tag approval, trial vs standard settlement w/ pre-settlement commission-tier selection, wallet hold/debit/credit conservation, cyclic refund negotiation, OCC stale-version 412, settlement reversal w/ clawback, reliability scoring, major validation/error paths.

## Step 7: Run Tests and Iterate — 2026-06-02T04:23:55.000Z

**Iterations run:** 3 (baseline + 3 fix-and-sweep cycles, with a final confirming sweep).

**Tests deleted:** None. Every failure traced to a test-bug (STEP 2) or an implementation gap (STEP 3), not PRD silence. All assertions kept (one tightened to track the PRD rule rather than an undetermined detail).

**Fixes applied to `test_helpers/`:** None — the broken preconditions lived in the test bodies, not the shared helpers.

**Fixes applied to `test_suite/` (STEP 2 test-as-a-whole consistency fixes):**
- `test_03_credential_and_tutor_lifecycle.py` — added missing `, 201` expected-status arg to 14 `create_subject` calls and 5 `create_tutor` calls that defaulted to expecting HTTP 200. PRD §4 line 197 verbatim: "Operations that create a new, standalone resource return a `201 Created` status code; this includes registering a tutor... creating a subject..." Implementation correctly returns 201.
- `test_03` — `test_tag_approval_requires_verified_credential` & `test_tag_stays_proposed_when_credential_not_verified`: fixtures registered an UNVERIFIED tutor then expected `ERR_SUBJECT_REQUIRES_CREDENTIAL`, but PRD §3.3 evaluates approval conditions in order (tag PROPOSED → tutor VERIFIED → gated credential) and surfaces the verification gap as `ERR_TUTOR_NOT_VERIFIED` first. Rewrote setup to make tutor VERIFIED via a credential on a non-gated subject, leaving the gated-subject credential UNDER_REVIEW so the credential gap is the actual failing condition.
- `test_04_bookings_and_scheduling.py` — `test_reschedule_request_then_confirm_updates_start`: (1) assertion compared `scheduled_start` as exact string `"...Z"` while impl normalizes UTC instants to 3 fractional digits `"...000Z"`; PRD pins the instant (§3.6) but is silent on serialization of that field → assertion now compares the parsed instant. (2) booking under test was the first for the (student,tutor) pair → a trial booking (hold capped to 30min/3000c) but test asserted standard 6000c rehold; added `consume_trial_slot(mk)` so the booking is standard.
- `test_02_refund_negotiation_and_reversal.py` — `test_arbitrated_grant_equals_award_and_penalizes_tutor`: escalated after a single tutor counter, but PRD §3.9 line 179 requires "round_count is at least 1" to escalate and a bare counter leaves round_count at 0 (only re-proposal increments it). Added a `repropose` within the monotone-narrowing band to reach round_count 1 before escalating.

**Fixes applied to `implementation/`:** None — every implementation behavior the failures touched was already PRD-faithful (201 creation codes, §3.3 error precedence, trial hold cap, round_count gate on escalation). No implementation check weakened or removed.

**Final sweep status:** All 8 parallel rounds passed 64/64 (passed == total == 64, 0 failed). Final green `results.{1..8}.json` persisted in `workspace/implementation/`.

**Orchestrator independent re-verification:** Ran a separate 8-round parallel sweep (verify.{1..8}.json) — all 8 rounds 64/64, 0 failed. Confirms green is not stale. verify files removed afterward; canonical results.{1..8}.json retained.

## Step 8: Finalize PRD — 2026-06-02T04:26:58.000Z

NOT skipped (Step 7 had non-zero test_suite/ fixes). Produced `workspace/PRD_FINALIZED.md`.

**PRD.md vs PRD_FINALIZED.md:** 286 lines vs 286 lines (0% line delta; one §3.5 paragraph extended in place). One edit total.

**Change:** §3.5 (Booking a Lesson) — insert — pinned that the server normalizes the client-supplied `scheduled_start` instant to an ISO 8601 UTC timestamp with three fractional digits (`...10:00:00Z` → `...10:00:00.000Z`) rather than echoing verbatim, and that the same normalization applies on confirmed reschedule — impl `app.py:760` (booking create) + `app.py:843` (confirm-reschedule), both via `db.iso_millis()` (`db.py:55`).

**Why only one edit:** four of five Step 7 items were pure test-setup bugs where PRD already determines behavior (201 codes stated verbatim §4 L197; §3.3 error precedence stated; trial hold cap §3.5 + rehold §3.6 stated; round_count≥1 escalation gate §3.9 L179 stated) — no edit. The one genuine PRD silence was the `scheduled_start` serialization (§2.4 pins `created_at` to 3 fractional digits but is silent on the domain datetime field `scheduled_start`).

**NO-NEW-MISMATCH search:** subject = serialization of datetime response fields. Enumerated db.iso_millis (3 digits + Z), db.now_iso, booking create scheduled_start (app.py:760), confirm-reschedule scheduled_start (app.py:843), activated_at, clock echo current_utc, created_at/updated_at, meta timestamp — all use identical 3-digit Z format; request-reschedule (app.py:809) does NOT write scheduled_start (only confirm does). Wording scoped to `scheduled_start` only (not a global datetime claim) to avoid contradicting §2.4's deliberate omission on `updated_at`.

## Step 9: Complete PRD — 2026-06-02T04:32:45.000Z

Always-runs full PRD-vs-implementation scan. Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md`.

**Line/char counts:** PRD_FINALIZED.md = 286 lines / 46,995 chars → PRD_COMPLETED.md = 286 lines / 49,922 chars (char delta +2,927; line count unchanged — all edits in-paragraph, no new paragraphs/sections).

**Counts:** 9 changes — 5 ambiguity-pins, 4 mismatch-revisions. (Doc-only; no impl/test edits — green status preserved.)

**Per-change list:**
- §3.11 Deterministic Clock — insert — ambiguity — pinned clock-set echo field `current_utc` (3-frac-digit ISO) in `data` + `200 OK` — app.py:89
- §3.2 Tutor Onboarding — insert — ambiguity — pinned integer balances/`active_subject_count` start at 0, `reliability_score` starts at 0.0 — app.py:210-211
- §3.1 Platform Configuration — insert — ambiguity — pinned no-active-policy fallback (trial cap 30, refund window 168, commission 0 bps both tiers) — services.py:139-143, app.py:746/921/999/1005/1172
- §3.7 Delivering — insert — ambiguity — out-of-range `actual_minutes` → `ERR_VALIDATION` after VERIFIED gate; deliver check order (state/clock→ERR_INVALID_STATE, then verify→ERR_TUTOR_NOT_VERIFIED); Session stores `actual_minutes` — app.py:911-919, serializers.py:74-78
- §3.6 Reschedule/Cancel/No-Show — insert — ambiguity — clock-window violations on request-reschedule/cancel/no-show → ERR_INVALID_STATE; request-reschedule order (state→reschedule-limit→clock) — app.py:813-820,863-866,884-887
- §3.9 Refund — revise — mismatch — `AGREED` is a transient waypoint, never persisted/returned; accept-counter/accept-offer move directly to terminal `RESOLVED_REFUND` atomically — app.py:1317-1321,1339-1343
- §3.9 Refund — revise — mismatch — refund-eligibility gate is `settlement_status == SETTLED` only; disputed session keeps `settlement_status = DELIVERED` (only `delivery_status`→DISPUTED) — app.py:1056-1057,1168
- §3.9 Refund — insert — ambiguity — "session's end" = booking `scheduled_start + planned_minutes` (not actual/billed), inclusive boundary, settlement-state check before window check — app.py:1166-1179
- §3.9 Refund — revise — mismatch — `supersedes_case_id` only existence-checked (ERR_REFUND_CASE_NOT_FOUND), not constrained to rejected case, stored verbatim — app.py:1156-1157,1192
- §4 Endpoint Definitions — insert — ambiguity — derived-ownership exception to global priority order: for refund-case open + session confirm/dispute, referenced session (and any supersedes_case_id) resolved for existence before derived parent-ownership check — app.py:982-985,1051-1053,1155-1162

---

## PIPELINE COMPLETE — 2026-06-02T04:32:45.000Z

All 9 steps finished. Final state: **64/64 tests pass across 8 independent parallel rounds** (orchestrator-verified). Task directory contains SCAFFOLD.yaml + 2 design YAMLs, test_helpers/ + test_suite/ (64 tests), workspace/implementation/ (Flask, in-memory, results.{1..8}.json all green), and PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md (the final contract). 0 tests deleted; 0 implementation fixes; Step 7 fixes were test-setup bugs only.
