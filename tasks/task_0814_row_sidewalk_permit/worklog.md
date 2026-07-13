# Worklog — task_0814_row_sidewalk_permit

Scenario: Right-of-Way & Sidewalk Obstruction Permit: application & site sketch, closure/obstruction & traffic-control plan, fee & restoration bond, inspection & restoration sign-off, utility-cut moratorium, encroachment agreement, violation/penalty, expiration

Difficulty: Expert

## Step 1: Create task directory — 2026-07-10T00:00:00.000Z

Created `tasks/task_0814_row_sidewalk_permit/` and `tasks/task_0814_row_sidewalk_permit/workspace/` (pre-assigned directory, no index auto-scan).

## Step 2: Generate scaffold (subagent) — 2026-07-10T00:00:00.000Z

All three files are complete, parse cleanly, and pass `scaffold_lint.py` with a clean verdict. Final consistency checks pass (no forbidden concurrency vocabulary, 18 difficulty instances across 9 rules, 24 active + 5 excluded corner instances).

## Summary

Generated a fresh **Expert**-tier scaffold for the Right-of-Way & Sidewalk Obstruction Permit scenario at `/home/ubuntu/github/CodingPRD/tasks/task_0814_row_sidewalk_permit/` — written purely from the scenario + skill spec (no sibling tasks consulted).

**Complexity profile:** primary `compliance_audit` + secondary `temporal_windowing`; layers = cascading side effects, rate/threshold triggers, derived-field reconciliation, optimistic concurrency; topology hybrid; state-machine shape cyclic; role model segregation-of-duties; immediate consistency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **10 entities:** Applicant, StreetSegment, SidewalkSpan, Permit (central aggregate), TrafficControlPlan, RestorationBond, LaneClosure, SidewalkObstruction, EncroachmentAgreement, ViolationNotice (immutable, `common_fields:false`). All FKs use the canonical `FK -> Entity.id` prefix; `api_prefix: "/"` so multi-collection FK reverse-reachability resolves.
- **6 state machines** with non-linear shapes: Permit (revision cycle UNDER_REVIEW↔RETURNED + branching terminal fan-out), LaneClosure (restoration cycle RESTORATION_PENDING↔RESTORATION_REJECTED), Bond/TCP branching forks, plus SidewalkObstruction and EncroachmentAgreement.
- **1 concurrency rule:** OCC on `Permit.version` for bond re-post/supersede (`expected_permit_version`, 412).
- **7 calculations:** dual-variant occupancy fee (estimated 40000 vs final overstay 49000), dual-variant bond refund (provisional 70000 vs final 55000), tiered occupancy with min-cap (mode a), per-component surcharge rounding-order (mode b, pinned 3807→56307 vs 3806→56306), escalating penalty with revoke threshold, moratorium-window, segment active-closure count. All literals verified by executing the formulas in Python.
- **24 validations** (priority-ordered), **36 endpoints** (incl. `/_clock/set_current_utc` defaulting to 2026-03-01T00:00:00Z), **24 errors**, **5 roles** (Applicant entity-backed; four opaque operational roles with an SoD gate on issue).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 18 instances — exactly 2 per each of the 9 difficulty rules, each with fully executable `setup_api_calls` chains, placeholder-closed `${var}` bindings, OCC via captured version, and pre-computed literal asserts.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 24 active corner instances + 5 `excluded_because` stubs (deduping §1.8-covered errors), across entities/state_machines/calculations/validations/rbac/cross_cutting/endpoints sections (creation, not-found, computed fields, invalid transitions, terminal lockdown, idempotency, each error trigger, RBAC/ownership denials, OCC stale-version, pagination, encroachment execute).

`scaffold_lint.py` verdict: **clean lint** — all §1.8/§1.9 calls conform to §1.5, and all §1.1 FKs have reverse-reachability.

Orchestrator verification: 1415 / 1261 / 1012 lines; all three `yaml.safe_load` OK. SCAFFOLD.yaml: 10 entities, 6 state machines, 7 calculations, 24 validations, 36 endpoints, 24 errors, 5 roles.

## Step 3: Copy shared files — 2026-07-10T00:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0814_row_sidewalk_permit/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD (subagent) — 2026-07-10T00:00:00.000Z

Generated `workspace/PRD.md` from the scaffold, written incrementally section by section.

**Sections written:**
- §1 Introduction (3 paragraphs — compliance/fiscal/temporal framing)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (all 5 roles + entity-backed/opaque identity prose), 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Properties & Versioning (ViolationNotice flagged `common_fields:false` — id + created_at only), 2.5 Fee Precision/Rounding, 2.6 OCC on bond posting, 2.7 Hierarchical Consistency & Revocation Cascades, 2.8 Nested Retrieval/Path Validation, 2.9 Validation Precedence (priority 1→12 ordering), 2.10 Logical Clock
- §3 Business Logic — 9 subsections (foundational resources → permit review loop → TCP+bond → issuance/occupancy fee → lane closures/moratorium → sidewalk obstructions/ADA → restoration/sign-off/bond refund → encroachment+violations/penalties → close-out/expiration/revocation)
- §4 Endpoint table (4 columns, 36 endpoints)
- §5 Error table (2 columns, 24 errors)

**Coverage:** 36 endpoints; 24 error codes (all mentioned in §2/§3 narrative, not just the §5 table). All 8 state machines (Permit, TCP, Bond, LaneClosure, SidewalkObstruction, EncroachmentAgreement transitions) and all 7 calculations (occupancy_fee estimated+final, total_permit_charge per-component surcharge, bond_required, bond_refund provisional+final waterfall, penalty_assessment escalation, moratorium_window, segment_active_closure_count) rendered as precise prose — no pseudocode/operators, no fuzzy words.

**Hard Contract reports:**

```
Contract 1 — Field-Name Coverage:
- entities[].fields + endpoint input/query/path identifiers: 66 distinct names required, 66 present, 0 missing
  (initial pass missed `to_iso8601`; added to §2.10, re-run clean)
Status: PASS

Contract 2 — Rule Coverage:
- validations[] priority ordering: expressed as explicit precedence chain in §2.9
- concurrency_rules[] OCC: bond-post write endpoint + expected_permit_version + ERR_STALE_PERMIT_VERSION/412 all named (§2.6)
- state_machines[].transitions: all named from→to, preconditions paired to error_ids, side-effects (incl. REVOKE cascade + count decrement asymmetry PLANNED-vs-ACTIVE) expressed
- calculations[]: all fully reconstructible from prose
- validations[] conditions: all matchable to error_id in §2/§3
- endpoints side_effects/applies_to: expressed
- field-level structured content + sibling-branch symmetry (estimated/final variants, PASS/FAIL sign-off, approve/reject): equal density
Status: PASS

Contract 3 — §3 Path Purity:
- backtick tokens scanned in §3; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0
Status: PASS
```

**Zero-Silence-Rule notes:** One notable scaffold tension surfaced and was handled faithfully — `segment_active_closure_count` is described as `count(status==ACTIVE)` yet the transition side-effects only decrement on RESTORED/VOIDED (not on ACTIVE→RESTORATION_PENDING). I transcribed the concrete increment/decrement side-effects (raised on activation, lowered on restore-or-void, never negative) plus the PLANNED-vs-ACTIVE/RESTORATION_PENDING void asymmetry, which is what the test suite will assert. All constants kept in exact integer cents (no lossy dollar conversion) to preserve the integer-cents contract.

Orchestrator verification: PRD.md = 264 lines; all 36 scaffold endpoint paths and all 24 error ids present verbatim.

## Step 5: Generate unit tests (subagent) — 2026-07-10T00:00:00.000Z

Done. Test infrastructure and suite are complete, compile cleanly, collect 60 tests, and pass the coverage + verbatim-citation + no-leakage audits.

**Stage 1 — `test_helpers/` (9 files)**
- `types.py` — enums + TypedDicts for all 10 entities. `ViolationNotice` correctly modeled as append-only (id + created_at only; no `updated_at`/`version`), all others carry common fields.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (36 endpoints incl. `set_clock`).
- `api_errors.py` — `ApiErrorId` enum + HTTP-status map, registered via `set_error_http_status_map`.
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (shared opaque-role constants + `make_applicant_headers` entity-backed builder), `fixtures.py` (composite setup: `setup_approved_permit`, `setup_issued_permit`, `setup_issued_permit_with_active_closure`, `setup_closure_signed_off_ready_for_release`, `setup_issued_permit_with_prior_violation`), `__init__.py` barrel export.

**Stage 2 — `test_suite/` (conftest + 9 files, 60 tests)**
- test_01 reference resources, test_02 permit lifecycle, test_03 TCP/bond/issue gates, test_04 fees & charges, test_05 lane-closure conflicts, test_06 restoration & bond release, test_07 bond refund, test_08 cascades & penalties, test_09 sidewalk & agreements.

**Coverage (design-index-only)**
- Queue A (Difficulty): all 18 instances covered, exactly 2 tests each (36 tests).
- Queue B (Corner): all 24 non-stub instances covered, 1 test each (24 tests).
- 5 corner `excluded_because` stubs NOT translated; all 5 `difficulty_instance` cross-references verified to resolve to real §1.8 instances.

**Instances skipped for PRD-first reasons: none.** Every non-stub instance had verbatim PRD coverage and unique derivability. The two validation-precedence instances (`state_beats_temporal_on_lane_closure_create`, `safety_beats_fiscal_on_issue`) are legitimately testable because PRD §2.9 states the fixed priority order explicitly.

**Audits passed:** every docstring carries a verbatim PRD citation (spot-checked ~45 distinctive substrings via literal `grep` of PRD.md — all present, incl. a bold-marker fix) and exactly one `Design:` tag; no `scaffold`/`§1.`/`Table` leakage; no `skip`/`xfail`/`skipif`; all numeric expected values (fees 40000/49000, cap 1000000, surcharge 3807/total 56307, refunds 70000/55000/25000, penalty 15000/threshold 37500, bond floor 50000, moratorium 2025-01-01/2027-01-01) recomputed against PRD formulas and match.

## Step 6: Generate implementation (subagent) — 2026-07-10T00:00:00.000Z

Orchestrator note: `test_helpers/` and `test_suite/` were physically moved out of the task tree for the duration of Step 6 (restored immediately after), preserving the pipeline's physical-isolation guarantee even though Step 5 ran first.

`start.sh` boots and serves (HTTP 200; the exit 144 is just from the background `pkill`). The implementation is complete and verified.

### Files created
- `start.sh` — guarded-install launcher (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — `flask`
- `app.py` — Flask app, `ApiError`/404/405/500 handlers, route registration, entrypoint
- `store.py` — in-memory dicts (per-boot fresh, never seeded), logical clock (default `2026-03-01T00:00:00Z`), UUID/ISO-millis helpers, `base_fields`/`touch`/`serialize`
- `envelope.py` — `meta`/`response_type`/`data` success + error envelopes, pagination meta
- `auth.py` — `X-User-ID`/`X-User-Role` authentication, role check
- `calc.py` — all calculations (occupancy fee, per-component surcharge, bond required/refund waterfall, escalating penalty, moratorium date arithmetic) using `Decimal`+`ROUND_HALF_UP`
- `routes.py` — all 36 endpoints via `register_routes(app)`

### Route count check
`py_compile` passes on all files. Running app reports **37 total url rules → 36 non-static endpoints**, matching the 36 endpoints in SCAFFOLD.yaml (plus Flask's static rule). Orchestrator independently confirmed: 36 non-static rules.

### End-to-end verification (all correct)
- Fee math: COMMERCIAL/LANE/10 days → est_fee 40000, surcharge 3734 (per-component rounding: 2900+544+290), total 55234; final fee over the true 19-day window = 67000
- Bond: required `max(50000, est*2)`=80000; provisional refund 79000; final refund 78000/forfeit 2000
- Segregation of duties → 403 `ERR_SEGREGATION_OF_DUTIES`; different reviewer issues fine
- Penalty escalation 15000→22500; cumulative 37500 auto-revokes: permit REVOKED, closure VOIDED, bond FORFEITED (held→0), segment `active_lane_closure_count` decremented to 0
- Auth precedence: wrong role→403, missing permit→404, stale bond version→412; missing auth→401
- Moratorium date: 2024-01-01 + 3yr (COMMERCIAL) = 2027-01-01

### PRD ambiguities resolved
1. **Segregation-of-duties ordering at issue**: PRD §2.9 places it in the authorization phase (before existence/state), while SCAFFOLD lists it at priority 7. Followed PRD §2.9 (checked right after permit existence, before state/TCP/bond). Since `assigned_reviewer_user_id` is only set in the APPROVED state, this never conflicts with the state check in practice.
2. **Bond forfeiture trigger on revoke**: PRD §3.9 says "if any closure is voided without ever having reached RESTORED" the bond is forfeited; SCAFFOLD only annotates the ACTIVE/RESTORATION_PENDING void transitions. Followed PRD literally — any voided (non-restored) closure, including PLANNED, triggers forfeiture; segment count only decremented for closures voided out of ACTIVE/RESTORATION_PENDING (per both docs).
3. **`ERR_INVALID_REQUEST` is last in precedence** (§2.9): body well-formedness checks are deferred until after auth/existence/date-range/state/business checks. Missing fields needed by earlier checks (dates, OCC version, refs) are checked conditionally (only when present) so the correct higher-priority error surfaces, and missing fields fall through to `ERR_INVALID_REQUEST` at the end.
4. **Superseding bonds**: modeled one active bond per permit via `permit.bond_id`; `GET /permits/{id}/bond` returns 0 or 1; re-post creates a new bond and advances `permit.version` by one (OCC).
5. **Permit `review_notes`**: the Permit entity has no such field, so `review_notes` on permit decision is accepted but not persisted (only TCP has a `review_notes` field).

Storage is in-memory only, nothing seeded at startup, and state is fresh on every boot (verified compatible with per-test-server restarts).

## Step 7: Run tests and iterate (subagent) — 2026-07-10T00:00:00.000Z

**Iterations run:** 2 (initial sweep found 2 failures; second sweep after fix was clean 8/8).

**Result:** All 8 rounds pass 60/60 tests.

**Root cause:** Two tests in `test_05_lane_closure_conflicts.py` (`test_overlapping_closure_rejected`, `test_adjacent_closure_allowed`) called `fixtures.setup_issued_permit` with a widened 19-day requested window (`2026-05-01` → `2026-05-20`) but relied on the fixture default `posted_cents=80000`. The fixture default is calibrated only for the default 10-day window. Per PRD §3.3, the required bond is `max(50000, 2 × estimated occupancy fee)`; for a 19-day COMMERCIAL/LANE window the estimated fee is 67000 cents, so the required bond is 134000 cents. The PRD-faithful implementation therefore correctly rejected the setup's bond post with `ERR_BOND_INSUFFICIENT` (HTTP 422), failing the closure tests in their setup phase.

**Fix applied (test_suite):** `test_suite/test_05_lane_closure_conflicts.py` — added `posted_cents=134000` to the two `setup_issued_permit` calls (lines ~33 and ~49) so the bond precondition is sufficient for the 19-day window. This is a STEP 2 test-setup fix (under-provisioned precondition); it makes the test more faithful to the PRD without weakening any assertion. All other widened-window callers (e.g. test_04) already pass explicit sufficient bonds.

**Tests deleted:** None. **Fixes applied to `test_helpers/`:** None. **Fixes applied to `implementation/`:** None — the implementation was correct.

**Operational note:** In this shell environment, native `wait`/foreground `sleep`/parallel-`&` batches return exit 144 and get their children killed. Each round was run via the Bash tool's `run_in_background` (4 at a time, two waves), blocking on a foreground `until [ -f results.N.json ]` poll loop instead of `wait`.

Orchestrator verification: `results.{1..8}.json` all report `passed=60 / total=60, failed=0, errors=0`.

## Step 8: Finalize PRD (subagent) — 2026-07-10T00:00:00.000Z

Not skipped: Step 7 recorded 1 `test_suite/` fix (skip condition requires 0 fixes of every kind).

**Line counts:** PRD.md = 264 lines, PRD_FINALIZED.md = 264 lines. **Delta: 0 lines (0%).** Files are byte-identical (`cmp` reports no difference).

**Changes:** None. Zero edits.

### Reasoning

The single `<step_7_diff>` item was a **test-setup under-provisioning bug**, not a PRD silence or PRD/impl mismatch. Two tests in `test_05_lane_closure_conflicts.py` posted a bond (`posted_cents=80000`) calibrated for a 10-day window while using a widened 19-day window; the PRD-faithful implementation correctly rejected it with `ERR_BOND_INSUFFICIENT`. The fix added the correct `posted_cents=134000` to the test setup. No implementation changes, no deletions, no weakened assertions.

### Verification performed (leading to the byte-identical conclusion)

- **Bond-required formula** — `implementation/calc.py:72-73`: `bond_required(est) = max(BOND_FLOOR_CENTS=50000, est * BOND_MULTIPLIER=2)`. Matches PRD §3.3 verbatim: "the larger of a fixed floor of 50000 cents and twice the permit's estimated occupancy fee."
- **Estimated occupancy fee input** — `implementation/routes.py:196-199` (`estimated_occupancy_for_permit`): uses `zone_class` + `primary_obstruction_type` over `requested_start_date` → `requested_end_date`. Matches PRD §3.4 estimated variant.
- **Bond-post gate** — `implementation/routes.py:561-566`: computes `required = calc.bond_required(est)`, rejects with `ERR_BOND_INSUFFICIENT` (422) when `posted < required`. Matches PRD §3.3.

### Per-edit pre-edit search log

No edits were committed. The mandatory verification search for the one subject examined:

- **(a) Subject:** the bond-sufficiency rule (required-bond formula + `ERR_BOND_INSUFFICIENT` gate).
- **(b) Impl paths enumerated/read:** `calc.py:16-17` (BOND_FLOOR_CENTS/BOND_MULTIPLIER constants), `calc.py:72-73` (`bond_required`), `routes.py:196-199` (`estimated_occupancy_for_permit`, requested-window input), `routes.py:560-566` (bond-post gate), and the second `ERR_BOND_INSUFFICIENT` site at the issuance gate `routes.py:440-441` (`bond["posted_cents"] < bond["required_cents"]`, matching PRD §3.4). All are consistent with the existing PRD prose.
- **(c) Wording adjustment:** none required — PRD already uniquely determines the behavior across every enumerated path.

**Conclusion:** PRD_FINALIZED.md correctly emitted as a byte-identical copy of PRD.md.

## Step 9: Complete PRD (subagent) — 2026-07-10T00:00:00.000Z

- **Source vs completed**: `PRD_FINALIZED.md` = 264 lines / 39,494 chars → `PRD_COMPLETED.md` = 264 lines / 40,337 chars (**+843 chars**, line count unchanged — all in-paragraph edits).
- **Counts**: 4 ambiguity-pins, 1 mismatch-revision.

### Changes
- **§2.3 Pagination — insert — ambiguity** — Pinned that `limit`/`offset` are clamped (not rejected): `limit`<1→1, >100→100, non-integer→default 10; `offset`<0→0, non-integer→0. (`routes.py:19-36`)
- **§2.8 Nested Resource Retrieval — insert — ambiguity** — Pinned that a body-referenced missing street segment→`ERR_SEGMENT_NOT_FOUND`, missing sidewalk span→`ERR_SPAN_NOT_FOUND`, and a missing sidewalk obstruction in the path→`ERR_CLOSURE_NOT_FOUND`. (`routes.py:89-100,131-135,326,630,765`)
- **§3.2 Permit decision — revise — mismatch** — PRD claimed the supplied `review_notes` are stored on a RETURNED permit; impl stores nothing (the `Permit` record has no `review_notes` field). Revised to say `review_notes` is accepted but not persisted, and pinned the `outcome` enum as `APPROVED`/`RETURNED`. (`routes.py:401-417`)
- **§3.3 TCP decision — insert — ambiguity** — Pinned the plan-decision `outcome` enum as `APPROVED`/`REJECTED`. (`routes.py:535`)
- **§3.7 Inspection sign-off — insert — ambiguity** — Pinned the `result` enum as `PASS`/`FAIL` and that `assessed_deficiency_cents` is optional (recorded only when present; otherwise the existing value, defaulting to 0, is retained). (`routes.py:728-753`)

### Cross-checks that already matched (no change)
Occupancy-fee / surcharge / bond / penalty / refund formulas and rounding (§2.5, §3.4, §3.7, §3.8), validation precedence (§2.9) across all creation endpoints, revocation cascade (§3.9), segregation-of-duties ordering at issue, all endpoint role sets vs. §4 table, logical-clock defaults, and immutable `ViolationNotice` shape all align with `implementation/` as written.

## Pipeline complete — 2026-07-10T00:00:00.000Z

Final state: 60/60 tests pass in all 8 stability rounds. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md (identical) → PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (conftest + 9 test files, 60 tests), workspace/implementation/ (8 modules + start.sh).
