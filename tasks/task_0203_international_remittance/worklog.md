# Worklog — task_0203_international_remittance

## Step 1: Create Task Directory — 2026-06-06T16:29:07.000Z

SKIPPED auto-scan per orchestration instructions. Using pre-allocated directory `tasks/task_0203_international_remittance/` (with `workspace/` already present). No new directory created.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-06T16:48:00.000Z

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` cleanly. I generated everything purely from the scenario description and the skill specification — no sibling tasks were inspected.

**Location:** `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (512 calls scanned across 18 + 30 active instances.)

**Scenario coverage (all aspects mapped):**
- Payout method (bank/cash pickup/wallet) → `Recipient.payout_method` + `Corridor.enabled_payout_methods` gate (`ERR_PAYOUT_METHOD_NOT_SUPPORTED`)
- FX quote & rate-lock margin → `Quote` machine (DRAFT→LOCKED→CONSUMED/EXPIRED), `quote_fee` + `recipient_amount` calcs with pinned margin-first rounding, TTL auto-expiry
- Corridor send limits → `corridor_limit_check` (per-transfer max, KYC-tier ceiling, rolling-window cap, all inclusive boundaries)
- Recipient KYC → `Recipient` branching-with-revert machine + `decide-kyc`
- Sanctions/compliance hold → `sanctions_score` weighted scoring, `SanctionsHit`/`ComplianceCase` (cyclic AWAITING_INFO loop + escalation), HELD/REJECTED bubble to Transfer
- Fee + exchange-rate disclosure → computed `Quote` fields + `LedgerEntry` audit
- Delivery tracking → `PayoutAttempt` + Transfer `delivery_status` axis
- Refund/cancellation → `Refund`, `refund_amount` dual-variant, compensating cascade

**Counts:** 12 entities · 4 state machines (Quote, Recipient, Transfer-parallel-axes, ComplianceCase-cyclic) + 2 OCC concurrency rules · 6 calculations (2 dual-variant) · 15 validations · 47 endpoints · 22 errors · 4 roles (segregation-of-duties: Agent/Officer/PayoutOperator + opaque Admin).

**§1.8 depth:** 9 Difficulty Rules × exactly 2 instances = **18 instances**, each with an empty-DB-executable `setup_api_calls` chain and code-computed literal asserts (e.g. fee_minor=899 at tier boundary, recipient_amount_minor=2778078 from pinned rounding order, ledger nets to 0 on compensated refund).

**§1.9 breadth:** **34 instances** (30 active + 4 `excluded_because` stubs), walking all 9 claim-extraction sections.

**Design notes / non-obvious decisions:**
- **Flat topology** (a §0.3-prioritized shape) drove `api_prefix: ""` so the lint derives every entity's collection segment from top-level `/collection/{id}` GETs; all 14 FKs use filtered-list reverse-reachability GETs.
- `ComplianceCase.sanctions_hit_id` was deliberately *not* declared with the canonical `FK ->` prefix (it's a denormalized back-pointer; the hit set is reverse-reachable via `/sanctions-hits?transfer_id=`), avoiding an unsatisfiable reverse-index requirement.
- Expert calibration is carried by **density**: a 2-axis parallel Transfer machine, a cyclic case machine, two distinct conserved-quantity invariants (funds vs corridor reservation), two different interval semantics (half-open rate-lock vs aggregate rolling-window capacity), and a depth-3 compensating cascade (case REJECT → transfer REJECTED → refund → ledger/reservation restore).
- One genuine mode-(b) rounding divergence lives in `recipient_amount` (margin-first 2778078 vs convert-first 2778077); `quote_fee` is the mode-(a) tiered-selection instance since an integer flat fee makes its own per-component-vs-sum order non-divergent.

## Step 3: Copy INSTRUCTION.md — 2026-06-06T16:50:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T16:55:00.000Z

Generated `workspace/PRD.md` — a 269-line PRD for the International Remittance (Wise/Western Union style) API.

**Structure (5 top-level sections):**
- §1 Introduction — 3 paragraphs (segregation-of-duties angle + minor/micro-unit conventions)
- §2 Global Specifications — 11 subsections (2.1 RBAC, 2.2 fixed verbatim envelope, 2.3 pagination, plus 8 domain-specific cross-cutting principles: versioning/common-fields, cascades, reference resolution, precision/scaling/rounding, send-limit & reservation discipline, conserved-funds ledger, OCC, logical clock)
- §3 Business Logic — 9 subsections organized by lifecycle/process (network config → onboarding → quoting/rate-lock → booking & funding → screening & compliance cases → dispatch/delivery → refunds → ledger invariant → validation ordering)
- §4 Endpoint table (4 columns, 47 rows = all scaffold endpoints)
- §5 Error table (2 columns, 22 rows = all scaffold errors)

**Scaffold coverage:** All 12 entities, all 4 parallel/cyclic state machines, all 6 calculations, all 15 validations with explicit priority ordering, all 22 errors, all 4 roles.

**Hard contracts — all PASS:** Contract 1 (Field-Name Coverage): 74 required names, 0 missing. Contract 2 (Rule Coverage): both OCC rules, all state transitions, all 6 formulas reconstructible, dual-variant divergences, cross-entity bubbles/compensating chain, 22 spot-checks all verified. Contract 3 (§3 Path Purity): 394 backtick tokens scanned, 0 slash-leading, 0 bare-method, 0 method+path.

**Notable decisions:** Pinned-rounding rules (floor-per-component-then-sum, margin-first conversion) and inclusive/exclusive boundary semantics rendered in precise prose. Endpoint input parameters scattered across §2.10/§2.11/§3. §2.2 byte-for-byte identical to canonical source.

## Step 5: Generate Unit Tests — 2026-06-06T17:10:00.000Z

Generated complete test infrastructure for `task_0203_international_remittance` (Expert-band International Remittance API).

### Test helpers (Stage 1) — 9 modules in `test_helpers/`
`types.py` (entity TypedDicts + 14 status enums; immutable audit records FxRate/SanctionsListEntry/SanctionsHit/LedgerEntry correctly omit `updated_at`/`version`), `api_client.py` (one method per endpoint incl. `/_clock/*`), `api_errors.py` (22 error IDs + HTTP-status map registered), `assertions.py` (per-entity assertions + ledger-net helper), `factories.py` (input-only payloads + canonical corridor block), `constants.py` (thresholds/ceilings/grace/canonical rate), `test_users.py` (four opaque-role headers), `fixtures.py` (composite chains: corridor+FX config, party onboarding, locked-quote, funded/screened/held/dispatched/failed-attempts transfer states), `__init__.py` barrel.

### Test suite (Stage 2) — 8 files, 64 tests in `test_suite/`
Counts: **34 queue-A (Difficulty)** + **30 queue-B (Corner)** = 64. Files: `test_01_quote_pricing` (11), `test_02_transfer_funding_limits` (9), `test_03_sanctions_screening` (7), `test_04_compliance_cases` (9), `test_05_dispatch_delivery` (8), `test_06_refunds_ledger` (7), `test_07_onboarding_crud` (9), `test_08_authorization` (5).

### Coverage vs. design indices
- **Queue A:** 17 of 18 difficulty instances translated, each with exactly 2 tests.
- **Queue B:** all 30 non-stub corner instances translated (≥1 test each); the 4 `excluded_because` stubs correctly not translated.

### Instances skipped (1)
- **`Difficulty/dual_variant_calc/sanctions_score_strict_vs_base_variant_diverges`** — fails unique-derivability. Asserts score 100 / HELD for a recipient in country RU under the *strict* screening variant, but PRD §2/§3.5 selects the strict variant "when the party's country is on the high-risk country list" and never enumerates that list. A PRD-only implementer would screen RU under base (score 30 → CLEARED), so the strict-only outcome is not pinned. No placeholder/xfail emitted.

### Validation performed
All 18 modules compile. C1 verbatim: all 75 quoted PRD fragments confirmed present. C4 tags: all 64 tests carry exactly one `Design:` line; every tag resolves. All asserted numeric literals (fees 799/899/1398, locked_rate 55561566, recipient amounts 2778078/5556156, scores 0/30/65/100, ledger nets) independently recomputed and match YAML. No scaffold leakage, no skip/xfail.

## Step 6: Generate Implementation — 2026-06-06T17:10:00.000Z

Built a complete Python + Flask implementation in `workspace/implementation/`. All state in-memory (module-level dicts in `db.py`); fresh `start.sh` boot wipes every byte. No entities seeded at startup. Verified clean against 106 manual assertions including a kill+relaunch state-wipe check.

### Files (21 source files + launcher)
- `start.sh` — guards `pip install` behind `import flask`, then `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000), foreground.
- `app.py` — Flask entry, blueprint registration, error envelope handlers.
- `db.py` — in-memory stores + logical clock. `errors.py` — error catalogue (21 IDs → HTTP). `response.py` — envelope, `req_` ids, 3-fractional-digit ISO timestamps. `middleware.py` — `X-User-ID`/`X-User-Role` auth + RBAC.
- `services/`: `common.py`, `calculations.py` (all 5 calc rules), `clock.py` (quote auto-expiry), `ledger.py`, `serializers.py` (computed `refundable_minor`).
- `routes/`: `config.py`, `parties.py`, `quotes.py`, `transfers.py`, `compliance.py`, `payouts.py`, `refunds.py`, `ledger.py`.

### Endpoints: 48 routes implemented (PRD §4 + GET/HEAD pairs)

### State machines: Quote (TTL auto-expiry), Recipient KYC (revision cycle), Transfer parallel axes (funding/compliance/delivery with retry guard), ComplianceCase cyclic (decide w/ cross-entity bubble + compensating refund chain).

### Calculations (verified to scaffold literals): quote_fee (tiered floor-per-component: 799/899), locked_rate/recipient_amount (margin-first: 55561566/2778078), sanctions_score (base vs strict; 30/65/100), corridor_limit_check (three inclusive ceilings + rolling-window), refund_amount (dual fee variant).

### Validations: PRD §3.9 priority order auth(400)→role(403)→existence(404)→body(422)→OCC(412)→state(409)→business rules. OCC on `expected_quote_version` and `expected_case_version`.

### ⚠️ One PRD inconsistency resolved (FLAG for Step 8/9 review)
PRD §3.7 says the FEE_REVERSAL ledger entry equals the refunded fee, but PRD §3.8 ("Ledger Conservation Invariant", the only machine-checkable `sum == 0` assertion) pins net = `fee_minor − fee_refunded_minor`. These cannot both hold. Impl made the **net** authoritative per §3.8 by writing `FEE_REVERSAL = fee_minor − fee_refunded_minor` (the retained fee), so a compliance-reject/delivery-failed transfer's ledger nets to exactly 0. `Refund.fee_refunded_minor` field still reports customer-facing refunded fee (799). Flagged in `services/ledger.py` code comment.

### start.sh boot
Reads `$PORT`, runs `python3 -c "import flask"` and pip-installs only when missing, then `exec python3 app.py` binding `0.0.0.0:$PORT` foreground. Server responds within ~0.6s; kill+relaunch fully wipes state.

## Step 7: Run Tests and Iterate — 2026-06-06T17:25:00.000Z

All 8 parallel rounds fully clean: 64 passed, 0 failed, 0 errors, 0 skipped in every round. The implementation was already in a passing state on the first verification sweep; the parallel sweep confirms no timing-sensitive flakiness across the union of all rounds. Independently re-verified by the orchestrator reading all 8 `results.{1..8}.json` (each total=64 passed=64 failed=0 errors=0 skipped=0).

- **Iterations run:** 1 (single 8-round parallel sweep; all rounds clean on first pass, no fix/rerun cycles).
- **Tests deleted:** None.
- **Fixes applied to test_helpers/:** None.
- **Fixes applied to implementation/:** None.

Notes: The known PRD §3.7/§3.8 inconsistency around the `FEE_REVERSAL` amount did NOT produce any failing refund/ledger test — the refund/ledger tests pass against the implementation's §3.8-authoritative net (`net = fee_minor − fee_refunded_minor`). (Flagged for Step 9 attention since §3.7 prose still says FEE_REVERSAL equals the refunded fee.)

## Step 8: Finalize PRD — SKIPPED — 2026-06-06T17:25:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). `PRD.md` already determined every behavior the implementation exhibits at all Step 7 sites. No `PRD_FINALIZED.md` produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-06-06T17:35:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan, starting from `PRD.md` (Step 8 skipped → no PRD_FINALIZED.md).

**File counts:** `PRD.md` 269 lines / 43,392 chars → `PRD_COMPLETED.md` 269 lines / 44,822 chars (char delta +1,430; line count unchanged — all edits in-paragraph).

**Counts:** 3 ambiguity-pins, 4 mismatch-revisions (7 edits across 7 paragraphs).

**Per-change list:**
- §3.7 — revise — mismatch — FEE_REVERSAL ledger entry pinned as the **retained fee** (`fee_minor − fee_refunded_minor`), not "the returned fee"; resolves the known §3.7/§3.8 inconsistency — `services/ledger.py:81-83`.
- §3.8 — revise — mismatch — FEE_REVERSAL entry corrected from "positive refunded fee" to "positive retained fee (`fee_minor` minus `fee_refunded_minor`)", net statement kept consistent — `services/ledger.py:81`.
- §3.5 — insert — ambiguity — Enumerated the high-risk country list (`RU`, `IR`, `KP`, `SY`, `CU`) selecting the strict name-matching variant — `services/calculations.py:26`.
- §3.5 — insert — ambiguity — Pinned the sender-block side effect on case REJECT: transfer with any `SanctionsHit` `subject_kind == SENDER` sets sender `status = BLOCKED` — `routes/compliance.py:127,137-146`.
- §3.4 — insert — ambiguity — Pinned transfer also stores `quote_id`/`recipient_id`; `sanctions_score` starts `null` until screening — `routes/transfers.py:67,78`.
- §3.3 — revise — mismatch — All disclosure fields empty/`null` in DRAFT until lock (mid_rate_micro, locked_rate_micro, fee_minor, recipient_amount_minor, total_pay_minor, locked_at, expires_at) — `routes/quotes.py:65-73`.
- §3.3 — insert — ambiguity — On lock, prevailing `mid_rate_micro` treated as 0 when corridor has no prevailing snapshot — `routes/quotes.py:138-139`.
- §3.2 — insert — ambiguity — submit-kyc allowed only from `UNVERIFIED`/`REJECTED` (else `ERR_INVALID_STATE`); state check before `kyc_doc_ref` presence check — `routes/parties.py:143-148`.

**Notes:** Left the §3.5 "MANUAL opened_reason" aside untouched (no MANUAL-case-creation endpoint exists). Country-component truncation, idempotent re-suspend, and fractional/negative clock seconds judged reasonably covered by existing prose and not pinned to avoid inventing behavior.

---

## Pipeline complete

All 9 steps finished. Final state: 64/64 tests passing across all 8 parallel stability rounds, zero fixes needed in Step 7, Step 8 skipped (no PRD divergence at test sites), Step 9 closed 7 residual PRD silences/mismatches via full impl scan. Deliverables: `SCAFFOLD.yaml` (+ DIFFICULTY/CORNER design indices), `workspace/PRD.md`, `workspace/PRD_COMPLETED.md`, `test_helpers/` (9 modules), `test_suite/` (8 files, 64 tests), `workspace/implementation/` (Flask, in-memory).
