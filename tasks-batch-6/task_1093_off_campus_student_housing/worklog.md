# Worklog — task_1093_off_campus_student_housing

Scenario: Off-Campus Student-Housing Marketplace: property & by-bed lease, roommate-match & floorplan, guarantor/cosigner & installment, academic-year term & turnover, university-partner & verification, summer sublet, amenity, payout

Difficulty: Expert

## Step 1: Create task directory — 2026-07-24T00:00:00.000Z

Pre-assigned folder used as-is: `tasks/task_1093_off_campus_student_housing/` (+ `workspace/`). Step 1 directory scan skipped per instruction.

## Step 2: Generate scaffold — 2026-07-24T03:51:00.000Z

All three files are complete, parse cleanly with `yaml.safe_load`, lint clean, and contain no forbidden concurrency vocabulary.

Generated a fresh **Expert**-tier scaffold for the Off-Campus Student-Housing Marketplace, built purely from the scenario description and the scaffold-generator skill (no sibling tasks consulted).

**Files (line counts):**
- `SCAFFOLD.yaml` — 3,181 lines (§1.0–§1.7 + constants + concurrency_rules)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,919 lines (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3,673 lines (§1.9)

**Scaffold surface:**
- Entities: 13 · Endpoints: 58 · State machines: 11 · Errors: 61 · Roles: 4 · Validations: 41 (priority-ordered) · Calculations: 14 · Concurrency rules: 2 (OCC)

**Design character:** flat topology; `temporal_windowing` × `multi_party_negotiation`; parallel state axes on Lease (`lease_status` × `funding_status`), a cyclic GuarantorApplication negotiation loop, compound Property posture, branching-with-revert Student verification. Two contrasting interval semantics (half-open bed slots with a 14-day turnover buffer vs. closed-interval aggregate amenity capacity), a dual-variant lease total (whole-month QUOTED vs. daily-prorated CONTRACTED) and dual-variant roommate scoring (pairwise-mean vs. lead-anchored), a floor-then-residual installment waterfall, a tier-on-gross/rebate-on-subtotal payout engine, and two conservation invariants (property money across payout/reverse; unit bed partition across reserve/cancel). Logical clock defaults to `2026-05-01T00:00:00Z`; segregation-of-duties on payouts.

**§1.8 instances:** 18 (all 9 Difficulty Rules × 2, each ≥2). **§1.9 instances:** 57 (54 full recipes + 3 `excluded_because` stubs).

## Step 3: Copy INSTRUCTION.md — 2026-07-24T03:52:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-07-24T04:00:00.000Z

Generated `workspace/PRD.md` (337 lines) from SCAFFOLD.yaml (design files withheld). §4 table has exactly 58 endpoint rows matching SCAFFOLD (58 endpoints).

**Structure:** §1 Introduction; §2 Global Specs (2.1 RBAC 4 roles + identity translations, 2.2 response envelope, 2.3 Pagination, 2.4 Common props/versioning, 2.5 Logical clock + 3-step ops checkpoint, 2.6 Money/precision/rounding, 2.7 OCC, 2.8 Bed rollups/posture/cascades, 2.9 Validation order/error precedence, 2.10 Nested retrieval + not-found map); §3 Business Logic (10 domain subsections); §4 endpoint table (58); §5 error table (61).

**Hard Contracts — all PASS:** Field-Name Coverage (114 entity fields + 67 endpoint inputs, 0 missing); Rule Coverage (all 61 error IDs surface; both parallel Lease axes, cyclic guarantor loop, dual-variant pricing QUOTED vs CONTRACTED, tiered payout w/ pinned rebate order, waterfall installment allocation, both OCC rules; every constant value in prose); §3 Path Purity (723 tokens, 0 leaks). Design files not opened.

## Step 5: Generate unit tests — 2026-07-24T04:20:00.000Z

**Stage 1 — `test_helpers/`** (9 modules): types, api_errors (65-entry enum), api_client (one method per endpoint), constants, factories, assertions (bed-partition + escrow-conservation invariant checkers), test_users (opaque operator headers + per-instance make_student_headers), fixtures (composite builders).

**Stage 2 — `test_suite/`** (conftest + 10 domain-named files).

**Coverage:** 92 test functions (102 pytest cases after parametrization), all collect cleanly. Queue A (Difficulty): 36 tests — 18/18 difficulty instances have ≥2 tests. Queue B (Corner): 56 tests — 54/54 non-stub corner instances have ≥1 test. Every docstring carries exactly one verbatim `Design:` tag; 0 dangling, no untagged/dual, no skip/xfail.

**Skipped:** the 3 `excluded_because` corner stubs (each owned by a difficulty instance already asserting the behavior). **One dropped sub-assertion:** in `role_without_endpoint_permission_returns_unauthorized`, a secondary check referencing a non-existent list-universities endpoint was omitted; the primary `ERR_UNAUTHORIZED` assertion kept.

## Step 6: Generate implementation — 2026-07-24T04:20:00.000Z

Complete Python + Flask in-memory REST API at `workspace/implementation/`. `app.py` — 1962 lines single-file; `start.sh` — guarded pip install + `exec python3 app.py`, foreground, `0.0.0.0:$PORT` (default 10000); `requirements.txt` — flask==3.0.3.

**Verification:** compiles clean, boots cleanly on fresh process, store starts empty (13 collections, no seeding). **Route count = 58** (introspected url_map). Worked-example math verified: dual-variant pricing (term_days 351, QUOTED 1,080,000 vs CONTRACTED 986,679); installment waterfall `[98667]×9 + 98676` sum 986,679; payout tiers (gross 98,667 → net 87,814, escrow conserved); roommate scores (PAIRWISE_MEAN 68 vs LEAD_ANCHORED 84); late fee strict-grace sweep; guarantor income floor → ERR_GUARANTOR_INCOME_INSUFFICIENT; SoD blocks same-admin payout approval (403). Envelope/edges correct. Timestamp discipline: system datetime fields render through logical clock in input's exact format (plain `Z`), created_at/updated_at/api_request_timestamp use wall-clock; UUIDs dashed. Half-open lease/sublet vs closed amenity/payout intervals; 14-day turnover buffer strict `<`.

NOTE: impl agent flagged it inadvertently killed sibling task_1094's bg server via a pkill/grep match — no lasting impact (that task self-restarts), but a host-hygiene caution for Step 7 sweeps.

## Step 7: Diagnose & fix (8-round per-test-server sweep) — 2026-07-24T11:30:00.000Z

Baseline sweep: 96/102 passed, SAME 6 failures every round (0 errors, 0 skips). Diagnosed each against PRD (source of truth). 3 fixes applied, 0 deletions. Post-fix sweep (4 waves of 2, sweep.sh): **all 8 rounds 102/102 passed, 0 failed, 0 errors, 0 skipped** — stable and clean.

**`implementation/` fixes (1):**
- `app.py:186` `render_logical()` — was echoing the input's exact format (plain `Z` when microsecond==0, `.000Z` otherwise), so logical-clock datetime fields (`current_utc` and every `*_at` system field) rendered as `2026-06-01T00:00:00Z` instead of `...000Z`. Fixed to ALWAYS emit three fractional digits, matching the PRD's system-wide ISO-8601 rendering convention (§2.3 `api_request_timestamp`, §2.4 `created_at`/`updated_at` — all "three fractional digits"). Verified every timestamp-field OUTPUT assertion in the suite expects `.000Z`; the plain-`Z` literals in tests are all `set_clock` INPUTS (`to_iso8601`), which the impl still parses fine. This is the recurring generated-timestamp format bug (cf. task_1060/1076/1088). Fixed `test_clock_cannot_move_backwards` and unblocked the `verification_expires_at == "...000Z"` asserts inside the verification-TTL tests.

**`test_helpers/` fixes (1):**
- `fixtures.py` — added top-level accessor `get_student(api, student_id)` mirroring the existing `get_lease`/`get_unit`/`get_property` (each `_d(api.get_x(id, ADMIN))`). The suite called `fx.get_student(...)` in 4 tests but the module only exposed `create_student`/`verify_student`; `api_client.get_student` already existed and was already used inside `fixtures.py:59,124`. Pure test-side plumbing — fixed the 4 `AttributeError` failures (test_03 verification ×3, test_10 RBAC ×1).

**`test_suite/` fixes (1):**
- `test_04_roommate_groups.py:142` (`test_group_lock_below_minimum_pairwise_score_rejected`) — expected `m5["match_score"] == 0` with comment "raw pair score -7 clamped to MATCH_SCORE_MIN", but the PRD §3.3 kernel between lead s1 (defaults 3/3/EARLY/no-smoke) and invitee s5 (1/5/LATE/smoke) is `100 − 12·2 − 8·2 − 25 − 30 = 5` (positive → no clamp). Impl's `5` is PRD-correct; the test's comment miscalculated the raw. Corrected expected value 0→5 and the comment. The test's PRIMARY purpose is unaffected: the 6-pair mean is `307/6 = 51.17 → 51 < 55`, so the lock is still refused with `ERR_GROUP_MATCH_SCORE_TOO_LOW` (group stays FORMING, `average_match_score` None).

**Deletions:** none. **test_suite/test_helpers ripple:** get_student accessor is additive (no behavior change to passing tests).

**Final sweep (post-fix, done-state re-parse):** all 8 `results.N.json` — total=102 passed=102 failed=0 errors=0 skipped=0. No skip/xfail in any round log.

## Step 8: Finalize PRD — 2026-07-24T11:34:00.000Z

Produced `workspace/PRD_FINALIZED.md` — minimal patch of `PRD.md` at Step-7 fix sites. Of the 3 Step-7 fixes, 2 were pure test-side corrections (get_student accessor; roommate match_score 0→5) where impl was already PRD-correct → no PRD edit. Only the timestamp-rendering fix warranted a PRD edit.

**1 edit — §2.5 (line 82), revise:** appended a clause pinning that the logical-clock `*_at` fields (signed_at, terminated_at, paid_at, decided_at, released_at, reversed_at, verification_submitted_at, verification_expires_at, verification_decided_at) AND `current_utc` render as ISO 8601 UTC instants with three fractional digits, exactly like `created_at`/`updated_at`. Traces to app.py:186 (render_logical), :718 (current_utc), :203 (clock_stamp). §2.5 line 86's plain-`Z` literal is the pre-set clock's semantic/input form (mirrored by tests' `to_iso8601` inputs), not a rendering statement — left verbatim, no conflict. Line count 337→337 (~0.3% char delta).

## Step 9: Complete PRD — 2026-07-24T11:42:00.000Z

Produced `workspace/PRD_COMPLETED.md` — full PRD-vs-`implementation/` scan starting from `PRD_FINALIZED.md`. 3 ambiguity-pins, 0 mismatch-revisions (no PRD passage contradicted impl). Line count 337→337; 59,809→60,245 chars (+436).

**Changes (3 inline ambiguity-pins):**
- §3.1 Verification re-request — insert — a re-request stamps `verification_submitted_at`/`verification_expires_at` but leaves any prior `verification_decided_at` unchanged (a re-request after REJECTED keeps that decision's timestamp until a later decision overwrites it) — app.py:944-947.
- §3.3 Placement — insert — a placed member's minted lease routes to `PENDING_GUARANTOR` when its `guarantor_required` is true, else `PENDING_SIGNATURE` (routed exactly as a solo submission by its own flag) — app.py:1178 (cf. test_04:234-236).
- §3.5 Guarantor DECLINE — insert — the `PENDING_GUARANTOR → CANCELLED` cascade stamps the lease's `terminated_at` to the current clock — app.py:1592 (cf. test_07:128).

**Considered, left unchanged (already PRD-determined):** payout APPROVE posture-vs-SoD ordering (governed by §2.9 priority ladder); sublet/amenity local error ordering (§2.9 governs cross-priority; tests exercise each in isolation); list default-sort insertion-order tiebreak (faithful projection of created_at ASC); per-endpoint query-filter sets (§2.3/§2.10 generic). All formulas, rounding, interval semantics, OCC guards, escrow/rollup cascades, error precedence already matched impl uniquely.

## Pipeline complete — 2026-07-24T11:42:00.000Z

Steps 1-9 done. Final state: 8/8 sweep rounds 102/102 pass (0 fail/err/skip); `PRD.md` → `PRD_FINALIZED.md` (1 edit) → `PRD_COMPLETED.md` (3 pins). Route count 58 == 58 scaffold endpoints.
