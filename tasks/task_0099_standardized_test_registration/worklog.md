# Worklog — task_0099_standardized_test_registration

Scenario: Standardized Test Registration Management (SAT/ACT/AP): test center capacity, accommodation requests (504/IEP), Super Score score reporting, tiered refund, Stand-by alternates, cross-state ID verification, CLEP credit recognition

Difficulty: Expert (passed only to Step 2 scaffold-generator; §0.4 Expert band — 10–15 entities, 20–32 endpoints).

## Step 1: Create task directory — 2026-06-02T21:16:00.000Z

Created tasks/task_0099_standardized_test_registration/ with workspace/ subdirectory at the fixed path (no ./tasks/ rescan/renumber per orchestration args).

## Step 2: Generate scaffold (Expert) — 2026-06-02T21:44:00.000Z

Generated all three scaffold artifacts for task_0099_standardized_test_registration at Expert difficulty, fully lint-clean.

Files written (all under tasks/task_0099_standardized_test_registration/):
- SCAFFOLD.yaml (§1.0–§1.7)
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8 — single key scaffold_difficulty_design)
- SCAFFOLD_CORNER_DESIGN.yaml (§1.9 — single key scaffold_corner_design)

Scale: 10 entities, 41 endpoints, 8 calculations, 16 validations, 16 errors, 4 roles, 2 OCC concurrency rules.
- Archetype: quota_allocation + compliance_audit; flat topology; parallel state-machine shape; peer_roles; immediate consistency.
- Entities: TestCenter, TestSession, Candidate, Registration, AccommodationRequest, StandbyEntry, ScoreReport, ScoreSend, CLEPClaim, IDVerification.

State machines (5 blocks across 4 entities):
- Registration axis 1 lifecycle (RESERVED→CONFIRMED→CHECKED_IN→NO_SHOW / CANCELLED) and axis 2 scoring (PENDING→SCORED→RELEASED / CANCELLED_SCORE) — parallel dimensions.
- AccommodationRequest — branching with a MORE_INFO_NEEDED↔UNDER_REVIEW cycle.
- StandbyEntry — linear with an OFFERED→DECLINED revert that re-promotes the next alternate.
- CLEPClaim — linear recognition.

Key calculations (literals pre-computed and pinned in test recipes): super_score (section-best 1440 vs best-sitting 1400), tiered_refund (14-day inclusive boundary → 4500/6000; 13 days → 3000), ap_fee_settlement (per-line-then-sum 15003 vs sum-then-round 15002), standby_promotion_score (FEE_WAIVER 300 > GENERAL 148), allotted_minutes (SAT ET50=201, ET100=268), id_verification (cross-state requires exact match), clep_credit (49→0/reject, 60→6, 70→9).

Difficulty coverage: all nine §0.5 rules satisfied with 2 differentiated instances each (18 §1.8 instances). §1.9 adds 33 active corner instances across all 9 claim-extraction sections plus 4 excluded_because stubs. OCC modeled as CREATE-with-supersede on TestSession.version (412); both write endpoints take expected_test_session_version and bump the version.

Linter: scaffold_lint.py → VERDICT clean lint — 41 endpoints, 10 entities, 18 §1.8 + 33 §1.9 instances, 350 calls scanned, all conform to §1.5, all 16 FKs have reverse-reachability.

Deviation flagged: endpoint count 41 > Expert ceiling 32, FK-reachability-forced (16 FKs across 10 entities each need a reverse-reachability GET) on top of the 7 distinct regulated sub-features. PaymentTxn entity dropped (ledger folded into Registration.refund_tier + TestCenter.net_revenue_cents). Matches documented "accept overage if lint-clean" guidance. Rationale recorded in SCAFFOLD.yaml header comment.

## Step 3: Copy shared files — 2026-06-02T21:46:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-02T21:53:00.000Z

Generated workspace/PRD.md (~273 lines, 5 top-level sections, 21 subsections; §4 endpoint table 41 rows; §5 error table 16 rows).

Hard Contracts — all PASS:
- Contract 1 (Field-Name Coverage): 56/56 entity fields + 5/5 endpoint request_body/query_param identifiers present verbatim, 0 missing.
- Contract 2 (Rule Coverage): all 7 calculations, both OCC rules (expected_test_session_version / ERR_STALE_SESSION_VERSION / 412), all state transitions across 6 machines, 16 validations with priority ordering, 3-deep cancel→standby cascade, three dual-variant traps (section-best-then-composite super score, days-before-test-date refund basis, per-line-round-then-sum AP fee). 27/27 spot-checks OK.
- Contract 3 (§3 Path Purity): 282 §3 backtick tokens scanned, 0 slash-prefixed/bare-method/method+path.

Confirmation: Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read; no sibling task consulted. PRD generated purely from SCAFFOLD.yaml + doc-generator skill.

## Step 5: Generate unit tests — 2026-06-02T21:55:00.000Z

Generated test infrastructure driven exclusively by the two design indices.

test_helpers/ (9 files): types.py (10 entity TypedDicts, common_fields per PRD §2.4, 14 status/role enums), api_client.py (one method per all 41 endpoints), api_errors.py (16 error IDs + HTTP status map), assertions.py, factories.py, constants.py, test_users.py (Candidate entity_backed w/ make_candidate_headers(id); other 3 roles opaque), fixtures.py (reserved/confirmed/checked-in/scored/released walks, accommodation review→approve chains, full-session-with-standby promotion targeting), __init__.py.

test_suite/ (conftest + 7 domain-named files): 69–70 test functions.

Coverage:
- Queue A (Difficulty): all 18 instances (9 rules × 2) covered, each ≥2 tests (36 difficulty-tagged tests).
- Queue B (Corner): all 33 non-stub active instances covered ≥1 each (33 corner-tagged tests). 4 excluded_because stubs correctly NOT translated; all 4 cross-references resolve.
- Skipped instances: 0. Every active instance passed the PRD-first two-condition filter.

Verification: every test carries exactly one Design tag (0 untagged/dual-tagged); 104 quoted PRD fragments verified verbatim; 0 skip/skipif/xfail; 0 scaffold-leakage; all 16 files byte-compile, import graph resolves against stub framework.

Note: OCC tests read live post-cancel session version via GET /test-sessions/{id} rather than arithmetic on captured values (robust to impl-specific version bump counts).

## Step 6: Generate implementation — 2026-06-02T21:55:00.000Z

Generated Python + Flask implementation (10 entities, 41 endpoints) in workspace/implementation/.

Files: start.sh, requirements.txt (Flask==3.0.3), app.py (blueprint registration, error handlers, 0.0.0.0:$PORT bind), db.py (in-memory store + simulated clock + id/timestamp helpers), errors.py (ApiError + 16-code catalog), response.py (meta/response_type/data envelope), middleware.py (X-User-ID/X-User-Role auth + require_roles RBAC), routes/ (centers, sessions, candidates, registrations, accommodations, standby, scores, clep, clock), services/ (common, calculations [8 calc rules], engine [seat/version/cascade/super-score], lookups, serializers).

Endpoint count: all 41 implemented, matching scaffold table.

Storage: in-memory only (Python dicts in db.Store, fresh each boot). No SQLite/file/JSON/tmp. No seeding/preloading (grep confirmed zero seed functions); empirically verified 17 sessions → 0 after start.sh restart.

start.sh: reads $PORT (default 10000), binds 0.0.0.0, foreground via exec python3 app.py, guards install behind `if ! python3 -c "import flask"` so per-test reboots are no-ops once Flask present; executable.

Self-verification: ~75 e2e checks passed (auth/RBAC ordering 401→403→404→400, envelope, pagination, OCC stale-version on register+claim, tiered refund FULL/PARTIAL_75/PARTIAL_50/NONE, AP per-line round-then-sum, accommodation review cycle + approval, cross-state vs same-state ID verification, check-in gates, ACT round-half-up composite, section-best Super Score + recompute on cancel-score, frozen-composite sends, standby promotion cascade w/ promoted_from_entry_id, session close NO_SHOW sweep + standby EXPIRE, CLEP credit steps).

Impl note: per state machine, CHECKED_IN → NO_SHOW close path has empty side-effects, so that seat is NOT released (only CONFIRMED → NO_SHOW releases, per PRD §3.1 "for each such forfeiture").

## Step 7: Run tests and iterate to green — 2026-06-02T22:30:00.000Z

Iterations run: 2 (baseline sweep + one fix batch, re-verified with a second full sweep).

Tests deleted (1):
- test_ap_fee_per_line_round_then_sum (test_suite/test_05_capacity_and_validation_priority.py) — STEP 1b unique-derivability failure (DEFAULT/COMPUTED-FIELD SILENCE). Test created a single AP registration (base_fee_cents=10001, fee_reduction_pct=0.5) and demanded amount_paid_cents == 15003, i.e. exactly 3 line items of 5001. Nothing in PRD (nor SCAFFOLD.yaml) fixes that an AP registration has 3 line items: Registration has no line-item-count/quantity field, create-registration payload carries none, PRD §3.3 only says "an AP order can bundle several exams ... each AP exam is a line item" without fixing a count. A faithful PRD-only implementer reasonably reads one registration = one seat = one line item (yielding 5001, confirmed by the retained passing single-line SAT test). Both divergent PRD-faithful implementations articulable → deleted. The genuinely PRD-covered per-line-round rule remains tested by test_single_line_fee_reduction_rounds_half_up_per_line.

Fixes applied to test_helpers/: none.

Fixes applied to implementation/:
- db.py — now_iso_ms(): derives created_at/updated_at from the simulated clock (store.get_clock_now()) instead of real wall-clock. Per PRD §2.11 the platform runs against a settable logical clock; standby recency bonus is now − created_at so created_at must share that timeline. Fixed test_promotion_score_value_fee_waiver_zero_recency (FEE_WAIVER created+read at clock T was returning 348=300+capped-48h because created_at was real wall-clock ~3 days behind; now correctly 300). Added process-global monotonic _seq stamped in stamp_create as a stable creation-order tiebreaker.
- services/serializers.py — _copy(): strips internal underscore-prefixed keys (_seq) so they never leak into API responses.
- services/common.py — sort_by_created_at(): same-millisecond ties break by _seq (insertion order) instead of random UUID, keeping list ordering deterministic now that many entities can share a simulated-clock instant.
- services/engine.py — promote_top_standby(): promotion tiebreak (promotion_score DESC, created_at ASC) uses _seq for same-millisecond ties, preserving "oldest entry wins a tie."

Final sweep (subagent): all 8 parallel rounds passed==total, 68/68 each, no flakiness.

Orchestrator re-verification: the subagent's per-iteration rm cleared results.*.json on exit, so the orchestrator re-ran the full 8-round parallel sweep independently. Result: all 8 rounds 68/68 (passed=68 failed=0 total=68), zero flakiness. results.{1..8}.json regenerated and persisted under workspace/implementation/.

## Step 8: Finalize PRD — 2026-06-02T22:34:00.000Z

Produced workspace/PRD_FINALIZED.md (cp of PRD.md + 3 inline edits). Line counts: PRD.md = 273, PRD_FINALIZED.md = 273 (all edits inline sentence additions, no new lines/sections; ~+870 chars across 3 paragraphs).

Changes:
- §2.11 The Simulated Clock — insert — server-minted created_at/updated_at are stamped from the simulated clock (same timeline as the "now" used for standby waited-hours/time differences), with wall-clock fallback before the clock is set — db.py:50-60 (now_iso_ms), db.py:37-40 (get_clock_now).
- §2.3 Pagination — insert — two resources sharing identical created_at are tie-broken by creation sequence (oldest created first) for deterministic list ordering — services/common.py:73-80 (sort_by_created_at).
- §3.6 Standby ranking — insert — equal promotion_score AND equal created_at broken by creation sequence (oldest created first), cross-referencing §2.3 — services/engine.py:65-130 (promote_top_standby), sort at engine.py:100.

Items in step_7_diff needing NO PRD edit: serializers.py _seq stripping (internal undeclared field; §2.4 already fixes public shape) and the AP-fee test deletion (pure derivability/fixture bug; PRD §3.3 already states per-line round-then-sum and "A single-seat registration that is not an AP bundle is simply one line item", which the impl matches at registrations.py:63).

## Step 9: Complete PRD — 2026-06-02T22:38:00.000Z

Produced workspace/PRD_COMPLETED.md (cp of PRD_FINALIZED.md + 6 inline ambiguity-pins). Source PRD_FINALIZED.md (273 lines, 46,357 chars) → PRD_COMPLETED.md (273 lines, 48,042 chars). Char-delta +1,685; no line-count change (all in-paragraph).

Counts: 6 ambiguity-pins, 0 mismatch-revisions (impl already matched PRD prose everywhere a behavior was uniquely described; only gaps were silences).

Changes:
- §3.1 (close sweep) — insert — ambiguity — CHECKED_IN → NO_SHOW sweep fires only when score_status still PENDING, releases no seat, no version bump (unlike CONFIRMED path); a scored CHECKED_IN reg untouched — routes/sessions.py:130-136.
- §3.3 (reservation) — insert — ambiguity — fee_reduction_pct must be fraction in [0,1] inclusive, else ERR_INVALID_REQUEST — routes/registrations.py:45-46.
- §3.3 (check-in) — insert — ambiguity — accommodated registration whose bound request is absent or not yet APPROVED → ERR_INVALID_STATE — routes/registrations.py:205-210.
- §3.6 (standby promotion) — insert — ambiguity — minted offer-hold field defaults: score status PENDING, amount_paid_cents 0, allotted_minutes = exam base, empty accommodation_request_id, amount_refunded_cents 0, null refund_tier — services/engine.py:104-116.
- §3.8 (score recording) — insert — ambiguity — exam_type taken from request body (not session), must be SAT/ACT else ERR_INVALID_REQUEST; section_scores must carry exactly canonical keys per exam, extras silently dropped; super_composite null at recording, computed only on release — routes/registrations.py:232-263.
- §3.9 (CLEP claim) — insert — ambiguity — clep_scaled_score integer in [20,80] inclusive, else ERR_INVALID_REQUEST — routes/clep.py:28-32.

Notable non-changes (verified consistent): ERR_REFUND_WINDOW_CLOSED imported but never raised by cancel (PRD §3.7 already states cancel always succeeds in NONE tier); clock endpoint empty-object response covered by §2.2; seat/version accounting on cancel/approval matches §3.5/§3.7.

## Pipeline complete — 2026-06-02T22:38:00.000Z

All 9 steps done. Final state: 10 entities, 41 endpoints, 68 tests (1 deleted in Step 7). Final 8-round parallel sweep: 68/68 all rounds, zero flakiness (orchestrator-verified). Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ + results.{1..8}.json}.
