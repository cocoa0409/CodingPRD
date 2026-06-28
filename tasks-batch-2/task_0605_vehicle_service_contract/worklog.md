# Worklog — task_0605_vehicle_service_contract

## Step 1: Create task directory — 2026-06-21T12:36:58.000Z

Created `tasks/task_0605_vehicle_service_contract/` and `workspace/` subdirectory (pre-assigned index, no scan). Confirmed `./INSTRUCTION.md` present for Step 3 copy.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-21T12:52:00.000Z

Generated the complete scaffold package for **task_0605_vehicle_service_contract** at the **Expert difficulty band**. All three required files were written and pass the official `scaffold_lint.py` with **`VERDICT: clean lint`**.

**SCAFFOLD.yaml** (§1.0–§1.7):
- **12 entities**: CoveragePlan, ReinsurancePool, Contract, AncillaryProduct, RepairFacility, Claim, ClaimLine, RepairAuthorization, Cancellation, LedgerEntry (append-only), ClockState, AuditEvent. Flat topology with cross-aggregate FKs.
- **5 state machines**: CoveragePlan (linear), Contract (cyclic ACTIVE↔LAPSED reinstatement loop + auto-EXPIRE), Claim (parallel dimensions: adjudication_status × payment_status), RepairAuthorization (branching DIRECT_PAY vs CUSTOMER_REIMBURSE + REVERSED compensation), Cancellation.
- **4 calculations** (3 with variants): `claim_adjudication` (labor-rate cap, round-per-line-then-sum), `claim_payout` (deductible floor + rental/towing), `pro_rata_refund` (dual-variant time-basis vs mileage-basis + free-look + dealer-unwind offset), `pool_surplus` (loss-reserve accounting identity).
- **1 concurrency rule**: OCC on Contract.version for repair-authorization disbursement.
- **44 endpoints** (incl. FK reverse-reachability GETs + `/_clock/set_current_utc` with the mandatory 2026-01-01 default), **27 error codes**, **5 RBAC roles** (peer-roles model; RepairFacility entity-backed, others opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): **9 rules × 2 = 18 instances**, all grounds resolve, all formula-derived asserts precomputed as literals (e.g., adjudicated 35349, total_payout 48349, PRO_RATA_TIME net 186333, PRO_RATA_MILEAGE net 139000, dealer-unwind net 137984, pool surplus −35349→−48349).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): **33 instances** (29 active + 4 `excluded_because:` stubs referencing valid §1.8 instances) spanning entities, state_machines, calculations, validations, endpoints, errors, rbac, cross-cutting layers (OCC), and consistency_model.

All 51 instance names unique across both design files; no forbidden concurrency vocabulary; all YAML parses cleanly.

## Step 3: Copy INSTRUCTION.md — 2026-06-21T12:52:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-21T12:56:30.000Z

`PRD.md` written (273 lines). 5 top-level sections, 18 subsections (§2 has 11 cross-cutting subsections: RBAC, response structure, pagination, common properties + logical clock, monetary precision, request validation, reference resolution, state-transition guard, reinsurance ledger/pool surplus, cascading side effects, OCC; §3 has 7 workflow subsections: catalog → contract sale → ancillary bundling → claim adjudication → authorize/disburse → cancellation/refund → adjudication priority + auditor view).

Hard Contract verification all PASS: 80 field/input/param identifiers verbatim, 50 enum/state values, all 27 error IDs present in prose. Validation priority ordering as explicit ordered chain (§3.7); single OCC rule (`expected_contract_version`/`ERR_STALE_CONTRACT_VERSION`/412); all three disburse cascade hops + reversal compensation; both contract-cancel cascades; all 4 calculations as precise prose with pinned rounding order. §3 path purity: 0 path tokens, 0 HTTP methods. §2.2 verbatim. Neither withheld design file opened.

## Step 5: Generate unit tests — 2026-06-21T13:06:41.000Z

**test_helpers/ (9 files):** types.py, api_client.py, api_errors.py (27 error IDs + status map), assertions.py, factories.py, constants.py, test_users.py (opaque shared constants for 4 roles + per-instance `make_repair_facility_headers` for entity-backed RepairFacility role), fixtures.py (composite chains: active/pending contract, claim SUBMITTED→UNDER_REVIEW→authorized→disbursed, canonical `setup_disbursed_standard` = 48349 cents, cancellation lifecycle), __init__.py.

**test_suite/ (conftest + 7 files, 65 test functions):** test_01 catalog/contract CRUD+RBAC+pagination; test_02 state machines (incl. cyclic lapse/reinstate); test_03 validations/errors; test_04 adjudication+payout; test_05 disbursement cascade/OCC/parallel-dims/reversals/pool-surplus; test_06 refund variants/free-look/boundaries; test_07 second covering test per difficulty instance.

**Coverage:** Queue A (Difficulty) all 18 instances × 2 = 36 tests; Queue B (Corner) all 29 non-stub × 1 = 29 tests. 0 instances skipped on PRD-first filter; 4 `excluded_because` corner stubs correctly NOT translated. 65/65 docstrings carry exactly one verbatim `Design:` tag; no skip/xfail; full suite collects 65 tests cleanly.

## Step 6: Generate implementation — 2026-06-21T13:06:41.000Z

**Files (13):** start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, guarded pip install, exec python3 app.py), requirements.txt (flask 3.0.3), app.py, db.py (in-memory dicts, logical clock default 2026-01-01T00:00:00Z), errors.py (27 codes + statuses), response.py (envelope + pagination), middleware.py (X-User-Role/X-User-ID auth + RBAC for 5 roles), common.py (validation, pagination, round-half-up Decimal, ledger posting + pool surplus recompute, audit), routes/{catalog,contracts,claims,cancellations}.py.

**Endpoints:** 44 (matches PRD §4). Verified: auth/RBAC priority 401→403→404→422, pagination bounds, adjudication (round-per-line-then-sum, labor rate=min(posted,cap)), payout (deductible floor + rental/towing caps), disburse 3-hop cascade + version bump, OCC on `expected_contract_version` (412), pool surplus from signed ledger, free-look FULL vs dual-variant pro-rata, cancellation cross-entity cascade, clock-driven validation. In-memory only, no seeding.

## Step 7: Run tests and iterate — 2026-06-21T13:16:55.000Z

Two consecutive clean 8-round parallel sweeps, all 65/65, 0 failures, 0 errors. Final sweep results.{1..8}.json all 65/65.

**Iterations run:** 3 sweeps total — 1 diagnostic baseline + 2 confirmatory (second and third both fully green).

**Baseline failures (union across 8 rounds):** 2 genuine deterministic failures every round; 4 transient `"API server could not be restarted before <test>"` setup errors (1–3 rounds each, never a real assertion failure) — pure 8×-concurrent CPU-contention boot-timeout artifacts that did not recur in either confirmatory sweep. start.sh already guards pip-at-boot (conditional install) and flask is preinstalled, so no code change warranted.

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `test_03_validations_and_errors.py` → `test_invalid_cession_pct_on_plan_activate`: test created a plan with `reinsurance_cession_pct=1.5`, expected creation to succeed, then asserted error at activation — but hit `KeyError: 'id'`. PRD §2.6 states the cession range check as a generic input validation (reject with `ERR_INVALID_CESSION_PCT`) with no qualifier limiting it to activation, while §3.1 restates it as an activation precondition — PRD admits two divergent faithful implementations, so activation-only assertion is not uniquely PRD-derivable. Per STEP 2, rewrote test to be MORE faithful to the dominant uniquely-derivable §2.6 sentence: supplying 1.5 at plan creation is rejected with `ERR_INVALID_CESSION_PCT`. Coverage preserved.

**Fixes applied to `implementation/`:**
- `routes/cancellations.py` → `refund_cancellation`: added structural state-transition guard ahead of the business check. Refunding an already-terminal cancellation (`REFUNDED`/`REJECTED`) now raises `ERR_INVALID_STATE` before the `ERR_CANCELLATION_NOT_APPROVED` business check, matching PRD §2.8 and the §3 priority order (structural `ERR_INVALID_STATE` precedes business `ERR_CANCELLATION_NOT_APPROVED`). `ERR_CANCELLATION_NOT_APPROVED` retained for the non-terminal `REQUESTED` case.

## Step 8: Finalize PRD — 2026-06-21T13:19:03.000Z

`PRD_FINALIZED.md` written (273 lines, 0% line delta — both edits inline, 2 lines modified).

- **§2.6 — revise** — cession-range check fires at plan creation (when supplied), in addition to the activation precondition — `routes/catalog.py:43-44` (creation) & `:85-86` (activation). PRD admitted reject-at-creation vs reject-only-at-activation; impl does both; pinned §2.6 explicit while preserving §3.1 activation restatement.
- **§3.6 — revise** — refund state-guard ordering: terminal cancellation (REFUNDED/REJECTED) → `ERR_INVALID_STATE`, non-terminal REQUESTED → `ERR_CANCELLATION_NOT_APPROVED` — `routes/cancellations.py:131-134`. PRD §3.6 said non-APPROVED universally yields `ERR_CANCELLATION_NOT_APPROVED`; pinned consistent with §2.8 transition guard + §3.7 priority order.

## Step 9: Complete PRD — 2026-06-21T13:22:47.000Z

`PRD_COMPLETED.md` written. Source PRD_FINALIZED.md (273 lines, 43,328 chars) → PRD_COMPLETED.md (273 lines, 46,199 chars); char delta +2,855, all in-paragraph. **Counts:** ambiguity-pins 7, mismatch-revisions 4.

- §2.1 RBAC — revise/mismatch — RepairFacility resources enforce no ownership comparison; role membership is the only gate — middleware.py:15.
- §2.4 Logical Clock — insert/ambiguity — `to_iso8601` required (missing/null → `ERR_INVALID_REQUEST`); set endpoint returns 200 with `data` = `current_utc` only — cancellations.py:162-172.
- §2.6 Request Validation — insert/ambiguity — enum string fields (`tier`, `product_type`, `reason`, `network_status`) stored verbatim, not value-set validated; only `line_type` range-checked — catalog.py:46-55, contracts.py:237-243, cancellations.py:27-33.
- §3.2 Contract computed fields — insert/ambiguity — `earned_premium_cents` = base × clamp(months_elapsed/term_months,0..1) round-half-up, recomputed on read for ACTIVE/EXPIRED/LAPSED/CANCELLED, 0 while PENDING — contracts.py:31-36.
- §3.2 Activation — revise/mismatch — pool ceded-premium not recomputed on read; impl posts only 0-amount placeholder — contracts.py:33-36,134-135.
- §3.2 Auto-expiry — insert/ambiguity — calendar-month-difference "months elapsed"; expiry check runs before earned-premium recompute — contracts.py:16-19,31-36.
- §3.2 Expiry reserve release — insert/ambiguity — "open claim" = `reserve_cents > 0` and `payment_status != PAID` — contracts.py:41-49.
- §3.3 Ancillary `gap_cap_cents` — revise/mismatch — stored verbatim regardless of product_type (not held at 0 for non-GAP) — contracts.py:228-240.
- §3.4 Claim line / Deny — insert/ambiguity — `line_type` ∉ {PART,LABOR} → `ERR_INVALID_CLAIM_LINE`; denial posts no RESERVE_RELEASE when reserve is 0 — claims.py:72-73,168.
- §3.5 Disburse reserve release — insert/ambiguity — no RESERVE_RELEASE when reserve already 0 — claims.py:264-266.
- §3.6 Refund — insert+revise/ambiguity+mismatch — refund-time contract-status check returns `ERR_CONTRACT_NOT_CANCELLABLE`; no REFUND_CLAWBACK when `net_refund_cents` is 0 — cancellations.py:136-147.

Pipeline complete: all 9 steps finished; final 8-round sweep 65/65 green across all rounds.
