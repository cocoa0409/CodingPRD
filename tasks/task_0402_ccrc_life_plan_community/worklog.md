# Worklog — task_0402_ccrc_life_plan_community

Scenario: Continuing Care Retirement Community (CCRC / Life Plan): entrance fee (refund tiers) & monthly service fee, independent→assisted→skilled continuum transition, contract type (Type A/B/C life-care), unit inventory & priority waitlist, second-person fee, health-center bed reservation, actuarial reserve disclosure, resident council

Difficulty: Expert (applies only to Step 2 scaffold generation — §0.4 Expert tier: 10–15 entities / 20–32 endpoints / 18–30 validations / 3+ calculations / 4+ state machines)

## Step 1: Create task directory — 2026-06-18T00:00:00.000Z

Created `tasks/task_0402_ccrc_life_plan_community/` with `workspace/` subdirectory. Task directory is fixed (pre-allocated), not auto-incremented.

## Step 2: Generate scaffold (Expert tier) — 2026-06-18T00:00:00.000Z

I read the full scaffold-generator skill specification (SKILL.md §0–§1.9, the claim-extraction guide, and `scaffold_lint.py`'s six checks), then generated a fresh Expert-tier scaffold for the CCRC / Life Plan Community scenario without consulting any sibling task. All three required files were written:

- **SCAFFOLD.yaml** (§1.0–§1.7, no design keys)
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (single key `scaffold_difficulty_design`)
- **SCAFFOLD_CORNER_DESIGN.yaml** (single key `scaffold_corner_design`)

**Final counts (Expert tier — all floors met):**
| Dimension | Count | Expert band | Status |
|---|---|---|---|
| Entities | 13 | 10–15 | ✓ |
| Endpoints | 55 | ≥20 floor | ✓ (rich read surface; floor cleared) |
| Validations | 22 | 18–30 | ✓ |
| Calculations | 5 | 3+ | ✓ |
| State machines | 5 | 4+ | ✓ |
| Errors | 35 | — | all referenced |
| Concurrency rules | 2 | — | OCC on Residency.version |

**Design highlights backing the Expert complexity:**
- **Calculations:** `entrance_fee_refund` (DECLINING/FIFTY/NINETY tiers with voluntary-vs-death variants, pinned per-month-then-multiply rounding order), `monthly_invoice_total` (Type A/B/C contract-dependent skilled per-diem), `actuarial_reserve_disclosure` (present-valued obligations + funded-ratio with admissions-freeze side effect), `waitlist_ordering` (period→priority→created_at, never id), `occupancy_period_accrual`.
- **State machines:** Residency (branching fork ACTIVE→{TERMINATED_VOLUNTARY, TERMINATED_DEATH}), CareTransition (independent↔assisted↔skilled continuum with back-step), BedReservation (HELD→{OCCUPIED, RELEASED, EXPIRED}), WaitlistEntry, CouncilResolution.
- **Cascade depth-3:** terminate → bed reservation RELEASED → skilled unit freed.

**Verification:**
- `scaffold_lint.py` final verdict: **`VERDICT: clean lint`** — all 481 §1.8/§1.9 calls conform to §1.5 (endpoint/role/payload/captures/OCC checks) and all 13 FKs have reverse-reachability GETs.
- §1.8 carries exactly **18 difficulty instances** (9 rules × 2, all differentiation clauses satisfied); §1.9 carries **37 active corner instances** plus excluded_because stubs.
- All `grounds:` references resolve to declared §1.1–§1.7 elements (0 unresolved); all instance names unique across both files; all `excluded_because` refs resolve; full enum closure on every state field; every error code referenced.
- All formula-derived assert literals were computed in code (e.g., refund 9,000,000 vs 5,000,000 voluntary/death divergence; rounding-order 900,004 vs 900,000; Type B 200,000; reserve funded_ratio 5,952 deficient-not-frozen boundary).

## Step 3: Copy shared files (bash) — 2026-06-18T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-18T00:00:00.000Z

**Output written:** `workspace/PRD.md` (294 lines, ~50KB). Domain: CCRC / Life Plan, prefix `/ccrc`, EXPERT band. Did NOT read either design file.

### Section structure
- §1 Introduction (3 paragraphs). §2 Global Specifications (11 subsections: RBAC, response envelope, pagination, common props/versioning, monthly clock & period accrual, enumerations, monetary precision/basis points, OCC on activation/termination, cross-entity cascades, nested retrieval & validation order, actuarial reserve & admissions freeze). §3 Business Logic (8 subsections, lifecycle-ordered, scattered constants). §4 4-column endpoint table. §5 2-column error table.

### Coverage counts
- 13 entities (Community, ContractPlan, Unit, Resident, Residency, SecondPerson, WaitlistEntry, CareTransition, BedReservation, MonthlyInvoice, RefundDisbursement, ResidentCouncil, CouncilResolution)
- 55 endpoints (matches scaffold exactly)
- 5 calculations — entrance_fee_refund (VOLUNTARY/DEATH variants, per-month-first eval order), monthly_invoice_total (TYPE_A/B/C surcharge, ASSISTED-into-base ordering, pre-increment skilled_days_used read), actuarial_reserve_disclosure (PV walk by created_at ASC, funded-ratio floor, freeze side-effect), waitlist_ordering (3-key tie-break, id never used), occupancy_period_accrual
- 5 state machines — Residency (branching, DEPOSIT_HELD forks, divergent termination branches), CareTransition, BedReservation, WaitlistEntry, CouncilResolution
- 35 error codes (all in §5 + surfaced in §2/§3 narrative)

### Hard Contract reports: Field coverage PASS, Rule coverage PASS, Path purity PASS (437 backtick tokens scanned, 0 path tokens in §3).

## Step 5: Generate unit tests — 2026-06-18T00:00:00.000Z

Generated complete test infrastructure from the two design indices only (no freelance discovery from SCAFFOLD.yaml).

### Tests emitted: 73 total
- **Queue A (Difficulty): 36 tests** — all 18 non-stub instances across 9 rules, each covered by exactly 2 tests (§1.8 minimum). Covers dual-variant refund/invoice calcs, pinned rounding order, branching terminate fork + back-stepping care continuum, depth-3 terminate→release→free and depth-2 waitlist place→reserve→re-rank cascades, two validation-precedence pairs, exact quorum/hold-window boundaries, two cross-entity gates, bed-capacity vs single-occupancy overlap pools, two compensating invariants.
- **Queue B (Corner): 37 tests** — all 37 non-stub instances, each covered by 1 test (entities 8, state_machines 12, calculations 3, endpoints 5, rbac 4, cross_cutting 1, consistency_model 1).

### Instances skipped: 6 (all `excluded_because:` stubs — not translated by design; each cross-ref verified to resolve to a real queue-A name). No instance skipped for PRD-coverage failure; every non-stub instance's asserted rule is verbatim-stated and uniquely-derivable in PRD.md.

### Files
- **test_helpers/**: `__init__.py`, `types.py`, `api_client.py` (47 endpoint methods), `api_errors.py` (35 error IDs + status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (3 opaque roles + entity-backed Resident builder), `fixtures.py` (7-tier composite setup helpers)
- **test_suite/**: `conftest.py` + 8 test files (`test_01`–`test_08`)

### Confirmations
- Every one of the 73 tests carries exactly one verbatim `Design:` tag (73 tests = 73 tags; no untagged, no dual-tagged); all tags resolve to real instances.
- All cited PRD sentences verified via literal grep of PRD.md (C1). Field names PRD-exact (`refundable_cents`, `care_surcharge_cents`, `base_service_fee_cents`, `is_admissions_frozen`, `funded_ratio_bps`); formula literals copied verbatim (9_000_000/5_000_000, 900_004, 570_000, 5952).
- No scaffold/Table N/§1.x leakage, no skip/skipif/xfail, entity-backed Resident identity via `make_resident_headers(resident_id)`. All 9 test_helpers + 9 test_suite files compile clean.

## Step 6: Generate implementation — 2026-06-18T00:00:00.000Z

Built complete Python + Flask implementation at `workspace/implementation/`.

### Files
- `start.sh` — reads `$PORT` (default 10000), guarded `pip install` (only when flask missing), `exec python3 app.py`
- `requirements.txt` (`flask==3.0.3`), `app.py` (routes, error handlers, `app.run(host="0.0.0.0", port=$PORT, threaded=True)`), `db.py` (in-memory dict stores + UUID/timestamp/request-id + monotonic `_seq`), `errors.py` (APIError + error_id→HTTP status), `response.py` (envelope helpers), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `services/common.py`, `services/calculations.py`, `services/waitlist.py`

### Coverage
- 13 entities, all ~55 endpoints from PRD §4.
- 4 calculation rules: entrance_fee_refund (pinned per_month=floor(G*bps/10000) once then ×m; DECLINING/FIFTY/NINETY; DEATH variant drops amortization for FIFTY/NINETY), monthly_invoice_total (ASSISTED surcharge folded into base before flat second-person; TYPE_A/B/C with pre-increment free-day read), actuarial_reserve_disclosure (PV over ACTIVE residencies by created_at ASC, floor on each PV + funded_ratio_bps, freeze when funded_ratio_bps < floor(target/2)), waitlist_ordering (enqueued_period_index ASC, priority_score DESC, created_at ASC; never id).
- 5 state machines: Residency (DEPOSIT_HELD→RESERVED/WAITLISTED→…→ACTIVE→TERMINATED_VOLUNTARY/DEATH with 3-hop cascade), CareTransition (PROPOSED→APPLIED/REVERTED, one-step continuum + SKILLED bed gate), BedReservation (HELD→OCCUPIED/RELEASED/EXPIRED + clock sweep), WaitlistEntry (PENDING→OFFERED→PLACED/WITHDRAWN + re-rank), CouncilResolution (DRAFT→OPEN→PASSED/FAILED with quorum + majority).
- OCC: `expected_residency_version` checked before state preconditions on activate/terminate → `ERR_STALE_VERSION` (412). Validation order: auth → role → path existence → body FK → body well-formedness → OCC → state/business; specific errors precede generic `ERR_INVALID_STATE`.

### Storage & startup
In-memory Python dicts keyed by id only — no SQLite, no JSON-on-disk, no /tmp cache. No module-scope seeding (every `db.*[...] = ...` lives inside a request handler). `start.sh` reads `$PORT`, binds `0.0.0.0`, runs foreground via `exec`. Fresh restart wipes all state to empty (verified 15 communities → 0 after reboot).

## Step 7: Test-and-iterate (8-round parallel sweep) — 2026-06-18T00:00:00.000Z

**Final state: 8/8 parallel rounds green at 72/72 each.** (Independently verified: all 8 results.*.json report passed==total==72.)

**Iterations run:** 2 (baseline sweep → 1 deletion → confirming sweep).

**Baseline:** All 8 rounds failed identically on a single test (`test_care_apply_on_reserved_residency_reports_not_active`) — a deterministic, non-flaky failure. The other 72 tests passed in every round.

**Tests deleted (1):**
- `test_suite/test_03_priority_boundary_cross_entity.py::test_care_apply_on_reserved_residency_reports_not_active` — **UNREACHABLE-PRECONDITION collapse** (STEP 1b unique-derivability). The test's setup proposed a care transition against a `RESERVED` residency and wrapped that propose call in `validate_success(..., expected_status=201)`. PRD §3.4 states verbatim: *"The parent residency must be `ACTIVE` at propose time, else `ERR_RESIDENCY_NOT_ACTIVE`."* A PRD-faithful implementation therefore correctly rejects propose-against-RESERVED with `ERR_RESIDENCY_NOT_ACTIVE` (the observed 409), so the test's 201 expectation is unsatisfiable. The residency state machine has no `ACTIVE → RESERVED` edge, making a `PROPOSED` transition whose parent is `RESERVED` an unreachable state combination under any PRD-faithful sequence — the scenario cannot be repaired without converting it into a duplicate of the already-present faithful sibling `test_care_apply_on_terminated_residency_reports_not_active` (propose while ACTIVE → terminate → apply → `ERR_RESIDENCY_NOT_ACTIVE`), which legitimately covers the apply-time gate. Scaffold rule that drove generation: `Difficulty/cross_entity_state_dependency/care_apply_requires_residency_active` (rendered into both a reachable terminated-path variant, kept, and this unreachable reserved-path variant, deleted).

**Fixes applied to `test_helpers/`:** None. The helper `reserve_residency_via_assign` (fixtures.py) was PRD-faithful; it produced a genuine RESERVED residency. The fault was entirely in the deleted test function's design — confirmed by the other 72 tests (which reuse those helpers) passing in all 8 rounds.

**Fixes applied to `implementation/`:** None. The implementation's propose-time `ACTIVE` gate is PRD-required (§3.4) and correct; weakening it would have violated the cardinal rule against removing PRD-required checks.

## Step 8: Finalize PRD — 2026-06-18T00:00:00.000Z

**No-op finalize.** `PRD_FINALIZED.md` is byte-identical to `PRD.md` (both 294 lines, MD5 `86074bbe62ee980a88c54b87c0630660`; verified by `diff -q` and md5). %-delta: 0%.

**Changes:** None.

**Why no edits:** The sole Step 7 diff item is a single test DELETION with explicitly recorded ZERO implementation fixes and ZERO test_helpers fixes. The diff attributes the failure to an unreachable-precondition test-design bug, and the subagent confirmed against `implementation/` that PRD §3.4 already verbatim-determines the relevant behavior:
- Propose-time gate — `app.py:670-671` `if residency["status"] != "ACTIVE": err("ERR_RESIDENCY_NOT_ACTIVE", ...)`; PRD §3.4 (PRD.md:158) states verbatim "The parent residency must be `ACTIVE` at propose time, else `ERR_RESIDENCY_NOT_ACTIVE`." — uniquely determined, no edit.
- Apply-time gate — `app.py:719-720` same check; PRD §3.4 "the parent residency must still be `ACTIVE`, else `ERR_RESIDENCY_NOT_ACTIVE`." — uniquely determined, no edit.

**Pre-edit search (performed even though no edit committed):** enumerated propose/apply/revert care-transition endpoints (`app.py:663-682`, `712-736`, `739-745`) and all residency `status` assignments (`app.py:369,399,467,573,634,654`) — confirmed residency reaches `RESERVED` only from `DEPOSIT_HELD` and `ACTIVE` only from `RESERVED`; no `ACTIVE → RESERVED` edge exists, so the deleted test's RESERVED-residency-with-PROPOSED-transition is an unreachable state combination. A no-op finalize is the correct result.

## Step 9: Complete PRD (full impl scan) — 2026-06-18T00:00:00.000Z

**Source vs. completed:** `PRD_FINALIZED.md` 294 lines / 50,645 chars → `PRD_COMPLETED.md` 294 lines / 51,461 chars. Char delta **+816** (no line-count change — all edits in-paragraph). Confirmed `PRD_COMPLETED.md` differs from `PRD_FINALIZED.md` (6 edits applied).

**Counts:** ambiguity-pins: 4 · mismatch-revisions: 2

**Changes:**
- **§2.1 (RBAC)** — insert — ambiguity — Pinned that an `X-User-Role` not among the four recognized roles (or empty) → `ERR_MISSING_AUTH`; `ERR_FORBIDDEN_ROLE` applies only to recognized-but-unauthorized roles. — `middleware.py:31-32`
- **§2.3 (Pagination)** — insert — ambiguity — Pinned clamp/default for out-of-range/malformed `limit`/`offset` (limit<1→1, >100→100, non-int→10; offset<0 or non-int→0; clamped/defaulted, never rejected). — `services/common.py:124-150`
- **§2.4 (Common Properties)** — revise — ambiguity — Removed "(or the implementation's initial value)" disjunction; pinned `version` begins at exactly 1 at creation. — `services/common.py:30`
- **§3.3 (Waitlist)** — insert — ambiguity — Pinned offer/place/withdraw each return the affected waitlist-entry object in `data` (not the residency). — `app.py:608,641,657`
- **§3.7 (Termination)** — insert — ambiguity — Pinned terminate returns the updated residency object in `data` (not the newly created refund disbursement). — `app.py:471`
- **§4 (Endpoint Definitions)** — revise — mismatch — General rule said modifying a resource returns 200; cast-vote actually returns 201 Created (updated resolution in `data`). Carved out the exception. — `app.py:1088`

**Notable non-changes (already pinned):** plan/community/council/unit defaults, refund-tier formula + pinned evaluation order, invoice assembly order with TYPE_B read-before-increment, actuarial PV/funded-ratio/freeze math, waitlist three-key ordering, termination cascade, validation-layer order (§2.10), OCC-then-state precedence (§2.8). Non-terminal-state errors for remove-second-person and settle-refund (both `ERR_INVALID_STATE`) already covered by §2.10 generic fallback.

---

## Pipeline complete

All 9 steps finished. Final state: **72/72 tests passing across all 8 parallel stability rounds**. Deliverables in place: SCAFFOLD.yaml (+2 design files), worklog.md, test_helpers/, test_suite/ (72 tests, all Design-tagged), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md (no-op), PRD_COMPLETED.md, implementation/ (+ results.1..8.json all green)}.
