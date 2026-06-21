# Worklog — task_0160_accounts_receivable_collections

## Step 1: Create task directory — 2026-06-05T00:00:00.000Z

Created `tasks/task_0160_accounts_receivable_collections/` and `tasks/task_0160_accounts_receivable_collections/workspace/` (pre-assigned path; auto-index scan overridden per orchestrator directive). Confirmed `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate scaffold (Expert) — 2026-06-05T00:00:00.000Z

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` cleanly. Here is the final report.

## Summary

Generated three lint-clean scaffold artifacts in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0160_accounts_receivable_collections/`:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key)

**Calibration: Expert band targeted** (§0.4) — and met on every axis: 12 entities (10–15), 45 endpoints, 20 error codes (18–30), 7 calculations with 3 dual-variant calcs, 5 state machines including a cyclic Dispute and a parallel-dimension Customer.

**Complexity profile:** primary archetype `ledger_reconciliation` + secondary `posture_driven_gating`; layers optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers; topology `flat`; state-machine shape `parallel`; role model `segregation_of_duties`; consistency `immediate`.

**Entities (12):** Customer, Invoice, Payment, PaymentApplication, Dispute, PromiseToPay, WriteOff, DunningSequence, DunningNotice, DunningPause, Statement, CashForecast.

**State machines (5):** Invoice (branching+revert, DISPUTED side-branch), Payment (apply/compensate), Dispute (cyclic reopen loop), PromiseToPay (keep/break/cancel), Customer (parallel `credit_status` × `collection_stage` dimensions).

**Calculations (7):** aging_bucket_assignment (dual-basis), cash_forecast (EXPECTED vs CONSERVATIVE), collection_priority_score (nonlinear ≥3-input), statement_finance_charge (pinned per-invoice-then-sum rounding), payment_waterfall_application (oldest-aging-first, created_at tie-break), credit_status_eval (>= threshold), collection_stage_eval.

**Validations:** 18 ordered rules (auth → existence → state → business safety/referential/constraint/temporal/fiscal). **Endpoints:** 45 (21 GET / 24 POST), every FK reverse-reachable, one `/_clock/set_current_utc` test-driving endpoint. **Errors:** 20, all triggerable. **Roles (4):** AR_MANAGER, AR_CLERK, COLLECTIONS_AGENT, AUDITOR (all opaque, segregation-of-duties on write-off). **Concurrency:** 1 OCC rule (`promise-create-stale-customer` on Customer.version, 412).

**§1.8 difficulty design:** 9 rule_ids × 2 instances = **18 instances**, each with a distinct differentiation (different entity domains, formula modes a/b, non-linear shapes, cascade triggers/depths, error-category pairs, metrics/endpoints, entity pairs, interval semantics, conserved quantities). Formula-derived asserts pinned to computed literals (e.g., finance charge 391, forecast EXPECTED 50000 vs CONSERVATIVE 82000, priority score 8.5, aging-30-day boundary B1_30, exposure==limit → HOLD).

**§1.9 corner design:** **44 instances total — 40 active + 4 `excluded_because` stubs**, covering all nine claim-extraction-guide sections (entities 12, state_machines 9, calculations 4, validations 5, endpoints 2, errors 3, rbac 3, cross-cutting layers 1+4 stubs, consistency 1).

**Verification performed:** all three files parse; `scaffold_lint.py` → `VERDICT: clean lint` (238 calls scanned, checks a–f pass); all grounds/named-transition refs resolve; all 62 instance names unique across both design files; all `excluded_because` references resolve; enum-value closure fixed (removed unproduced `Payment.REVERSED`, `PromiseToPay.SUPERSEDED`, `DunningPause.CANCELLED`); every error triggerable; no forbidden concurrency vocabulary; file split honored (neither design key leaks into SCAFFOLD.yaml).

One note: endpoint count (45) sits above the soft Expert ceiling of 32 — driven by the scenario's nine mandated sub-workflows (each entity's FK requires a reverse-reachability GET per lint check (f), plus per-resource retrieval reads). The §0.4 upper bounds are explicitly guidelines; every endpoint earns its place via a state transition, FK-reverse channel, or retrieval claim, and the surface is otherwise lean.

## Step 3: Copy shared files — 2026-06-05T00:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-05T00:00:00.000Z

Generated `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0160_accounts_receivable_collections/workspace/PRD.md` (274 lines) from the task's `SCAFFOLD.yaml` and the doc-generator skill spec.

**Confirmation — neither design file was read.** I did not open, grep, or reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`, and I did not look at any sibling task. The PRD was generated purely from this task's `SCAFFOLD.yaml`, the skill spec, and the shared `section-2.2-response-structure.md` fixed block.

**PRD section list:**
- 1. Introduction
- 2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim fixed block)
  - 2.3 Pagination
  - 2.4 Common Resource Properties and Identity
  - 2.5 Nested Resource Retrieval and Reverse Reachability
  - 2.6 Derived Balances, Posture Cascades, and Consistency
  - 2.7 Credit Posture and the Credit Hold Gate
  - 2.8 Segregation of Duties on Write-Off Approval
  - 2.9 Optimistic Concurrency Control on Promise Creation
  - 2.10 Monetary Precision and Rounding
- 3. Business Logic & Workflows
  - 3.1 Opening Accounts and Issuing Invoices
  - 3.2 Aging Classification
  - 3.3 Applying Cash: Payments, Short-Pays, and Reversals
  - 3.4 Disputes and Deductions
  - 3.5 Promises to Pay
  - 3.6 Write-Offs and Bad Debt
  - 3.7 Dunning: Sequences, Runs, Notices, and Pauses
  - 3.8 Statements
  - 3.9 Cash Forecasting
  - 3.10 Validation Ordering and the System Clock
- 4. Endpoint Definitions (4-column table, all 45 endpoints)
- 5. Error Code Catalogue (2-column table, all 20 error IDs)

**Hard Contract results (verified mechanically):**
- Contract 1 (Field-Name Coverage): 62 required field/param names checked, 0 missing — PASS
- Contract 2 (Rule Coverage): all 6 customer/invoice/payment/dispute/promise/write-off state machines, both customer parallel dimensions, all 6 calculations (aging, cash forecast EXPECTED/CONSERVATIVE, priority score, statement finance charge with pinned per-invoice-then-sum order, payment waterfall, credit/collection eval), the priority-ordered validation chain, the OCC rule (write endpoint + `expected_customer_version` + `ERR_STALE_VERSION`/412), and SoD all expressed in prose — PASS
- Contract 3 (§3 Path Purity): 425 §3 backtick tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path combos — PASS

Additional checks confirmed: §2.2 matches the source byte-for-byte, all 20 error IDs and all 31 state/enum values appear in narrative, and the prose contains no fuzzy/approximating words and no leaked pseudocode operators.

## Step 5: Generate unit tests — 2026-06-05T00:00:00.000Z

All infrastructure is generated, audited, and internally consistent. Here is the final report.

## Summary

Generated complete test infrastructure for `task_0160_accounts_receivable_collections` purely from the four inputs + the unit-test-generator skill spec. Every test translates exactly one design-index instance and carries a verbatim PRD citation plus a single `Design:` tag (all 99 cited quotes verified verbatim against PRD.md; all 73 tests carry exactly one tag with the Design line last).

**test_helpers/ (9 files):** `__init__.py`, `types.py`, `api_client.py` (45 endpoint methods), `api_errors.py` (20 error IDs registered with the framework status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`. DunningNotice/CashForecast correctly modeled as light records (id + created_at only); all four roles are `opaque`, so shared header constants plus per-operator builders (for the write-off SoD check) are emitted.

**test_suite/ (11 files):** `conftest.py` + `test_01`…`test_10` organized by domain concern (entities CRUD, aging/credit, payments/applications, disputes, write-offs/cascade, promises, dunning, statements/forecast, customer posture, access/errors).

**Total tests: 73** — Queue A (Difficulty): 34; Queue B (Corner): 39.

**Coverage:** 17/18 difficulty instances at ≥2 tests; 39/40 non-stub corner instances at ≥1 test. All 4 corner stubs correctly left untranslated (their `difficulty_instance` pointers all resolve to real, covered difficulty instances). No tags reference non-existent instances; no skip/xfail markers; no scaffold leakage.

**SKIPPED (2 instances, both PRD unique-derivability failures):**

- *Difficulty / combinatorial_formula / `collection_priority_score_nonlinear_promise_penalty`* — the asserted score 8.5 requires `collection_stage == COLLECTIONS` after a dunning run, but PRD §3.7 only states a dunning run moves the stage `CURRENT → DUNNING`. A faithful PRD-only implementer would compute the score with stage DUNNING (yielding 7.0), so the literal 8.5 is not uniquely derivable. (Consequence: rule `combinatorial_formula` has only its other instance, 1 test — an accepted PRD-first shortfall; no second test was invented.)
- *Corner / calculations / `finance_charge_excludes_current_bucket_invoices`* — asserts `finance_charge_cents == 0` based on the invoice being CURRENT on the **due-date** basis, but PRD §3.8 pins the finance charge to the **invoice-date** basis, on which the same invoice (invoice_date 2026-04-15, period_end 2026-05-01 → 16 days) is B1_30 and would contribute 750. The asserted 0 contradicts PRD prose, so a correct implementation would fail it.

Both gaps are PRD/design defects surfaced by the two-condition filter, left as gaps per the design-index-only contract.

## Step 6: Generate implementation — 2026-06-05T00:00:00.000Z

All clean. The implementation is complete and verified.

## Summary

Built a complete Python + Flask implementation of the Accounts Receivable & Collections API in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0160_accounts_receivable_collections/workspace/implementation/`.

### File list
- `start.sh` — foreground launcher (guarded pip install, `exec python3 app.py`)
- `requirements.txt` — `flask==3.0.3`
- `app.py` — entry point: blueprint registration, error handlers, `/ar/health` probe, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")))`
- `db.py` — in-memory dicts + override-able system clock + UUID/ISO helpers
- `errors.py` — `ApiError` + full §5 error-id→HTTP-status catalog
- `response.py` — `meta`/`response_type`/`data` envelope (verbatim §2.2)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth + RBAC
- `timeutil.py` — ISO 8601 parsing to epoch ms
- `services/` — `common.py` (stamping, parsing, pagination, rounding), `domain.py` (aging, recompute cascade, calculations, serialization), `lookup.py` (existence checks)
- `routes/` — `customers.py`, `invoices.py`, `payments.py`, `disputes.py`, `promises.py`, `writeoffs.py`, `dunning.py`, `statements.py`

### Endpoint count
**45 PRD endpoints** (44 functional from §4 + `POST /_clock/set_current_utc`), plus 2 health probes. All cross-checked against the §4 table via the live url_map.

### Storage / reset
Pure in-memory module-level dicts in `db.py`, keyed by UUID. Nothing is seeded, preloaded, or written to disk (verified: no sqlite/json.dump/pickle/file-write). Verified empirically — 15 customers before reboot, 0 after — so every byte of state is wiped on each `start.sh` re-invocation.

### start.sh / PORT
Reads `$PORT` (default 10000), binds `0.0.0.0`, runs in foreground via `exec`. The pip install is guarded on `python3 -c "import flask"` to avoid contention during concurrent per-test reboots. Verified: launched via `bash start.sh` with `PORT=18161`, bound to all addresses, full smoke suite passed.

### Verification
Five smoke suites (~70 assertions) all pass: auth ordering, credit-hold gate (inclusive boundary), short-pay/reversal invariant, dispute lifecycle + DISPUTED branch, write-off SoD + dispute-block, dunning run + priority score, auto-apply waterfall, promise OCC/overlap/evaluate KEPT&BROKEN, pause 1-day-buffer, statement per-invoice finance charge, both forecast methods, pagination, and error-priority precedence.

### Interpretation calls
1. **Broken-promise → `credit_status` WATCH (the one genuine ambiguity).** §3.5 says a BROKEN promise sets `credit_status` to WATCH-if-GOOD, but §2.7/§3.1 say `credit_status` is derived purely from exposure and recomputed on read — which would erase that WATCH. To honor both, I record an internal sticky `watch_floor` flag (not exposed in output) that raises GOOD→WATCH during recompute while HOLD still overrides. This keeps the §3.5 effect observable across subsequent reads.
2. **`collection_stage` not recomputed on customer GET.** §3.1 lists only `exposure_cents`, `total_open_balance_cents`, `credit_status` as recomputed on read — so GET customer preserves the last-set `collection_stage` (e.g., a dunning run's CURRENT→DUNNING is not silently overwritten by the worst-aging eval).
3. **`applied_payment_cents`** (computed, no setter endpoint): derived on demand from the customer's payments whose `received_at` falls in the promise's half-open window.
4. **Statement `opening_balance`**: "prior statement's period_end total_open_balance" implemented by snapshotting each statement's live `total_open_balance_cents` and using the most recent prior statement's snapshot (0 if none).
5. **Dunning channel enum** (not enumerated in the scaffold step schema): used `{EMAIL, PHONE, LETTER, SMS}`; invalid values yield `ERR_INVALID_ENUM`.
6. **Unknown role string** → treated as malformed authentication (`ERR_UNAUTHENTICATED` 401), since only the four named roles are recognized.

## Step 7: Test/fix iteration loop — 2026-06-05T00:00:00.000Z

Clean 8-round parallel sweep achieved: all 8 rounds report 73/73 passing.

## Summary

**Iterations run:** 2 (initial sweep surfaced 1 failure; second sweep after the fix was clean).

**Tests deleted:** None. The single failing test was PRD-faithful and uniquely derivable.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:**

The only failing test was `test_customer_version_increments_on_each_mutation` (test_06_promises.py), which asserts a customer's `version` goes 1 → 2 → 3 across create → hold → release-hold. It failed with `assert 3 == 2`: the `hold` operation was incrementing `version` twice.

Root cause: a single logical customer operation was producing two version increments. The `hold`/`release-hold` routes (and similarly the promise-create and write-off-approval cascades) called `touch(customer)` explicitly (+1), then `domain.recompute_customer(...)`, which calls `touch` again (+1) whenever a derived field such as `credit_status` changed. Setting `manual_hold` flips `credit_status` GOOD → HOLD, so the recompute double-counted the same mutation. PRD §2.4 states version "increments by one on every mutation of the resource," and §2.7/§2.9 describe hold/release/promise-create each as one customer mutation.

- `services/domain.py` — `recompute_customer`: added an `already_touched` parameter. When set, the function still refreshes the derived fields (`exposure_cents`, `total_open_balance_cents`, `credit_status`, `collection_stage`) but suppresses the additional `touch`, so a caller that already counted the operation as one mutation gets exactly one version increment.
- `routes/customers.py` — `hold` and `release_hold`: pass `already_touched=True` to the recompute call (these routes already `touch(c)` explicitly).
- `routes/promises.py` — promise `create`: pass `already_touched=True` so a successful create increments the customer's `version` by exactly one, per PRD §2.9.
- `routes/writeoffs.py` — write-off approval: pass `already_touched=True` (route already does an explicit `touch(customer)` for the bad-debt update), so the approval is one customer mutation.

Cascade sites that touch a *different* entity (invoice/payment/dispute) and then separately recompute the customer were left unchanged — those are genuinely two distinct entity mutations and correctly bump each entity once.

Results files cleaned up after the final clean sweep. No tests were weakened, skipped, or deleted; no PRD-required checks were removed; storage remains in-memory.

## Step 8: Finalize PRD — 2026-06-05T00:00:00.000Z

## Summary

**Line counts:** PRD.md = 274 lines, PRD_FINALIZED.md = 274 lines. Delta = 0 lines (+0.0%). The single change is a within-line revision of §2.6 (line 99) that inserts two clarifying sentences into an existing paragraph.

**Changes (one bullet):**
- §2.6 (Derived Balances, Posture Cascades, and Consistency) — revise — Pinned that a single logical operation counts as exactly one customer `version` increment however many derived fields its recomputation alters: when the operation already mutates the customer directly (place/release manual hold, create promise, approve write-off) the version bumps once for the whole operation and the derived-field recomputation adds no second increment even when it flips `credit_status`/`collection_stage`; carved out cascade-only sites (operation mutates a different entity and the customer changes solely through the cascade) where the recomputation itself is that customer's one increment. — `services/domain.py:182-211` (`recompute_customer` `already_touched` param), with callsites `routes/customers.py:83-84,94-95`, `routes/promises.py:66-67`, `routes/writeoffs.py:94-95`.

**Why this is the only edit:** The entire step_7_diff is a single fix — a `hold` operation was double-counting `version` (1→3 instead of 1→2) because it both `touch`ed the customer and let `recompute_customer` `touch` again when `credit_status` flipped GOOD→HOLD. PRD §2.4 ("increments by one on every mutation") and §2.6 ("Each such recomputation that alters the customer ... increments the customer's `version`") are internally in tension: read literally, §2.6 double-counts within a single operation. The implementation resolves the ambiguity by treating the *operation* as the mutation unit. §2.9 and §3.5 already pin promise-create to "+1" explicitly, so no edit was needed there; the §2.6 clarification now explains why the accompanying stage recompute adds nothing. No edit to §2.7/§3.6 was needed because the new §2.6 rule governs hold/release and write-off approval directly.

**Per-edit pre-edit search log:**

*Edit (§2.6 line 99):*
- **(a) Subject:** number of customer `version` increments produced by a single operation that both directly mutates the customer and triggers a derived-field recomputation.
- **(b) Impl paths enumerated/read:** `services/common.py:28-33` (`touch` = +1); `services/domain.py:182-211` (`recompute_customer`, `already_touched` suppresses the second touch) and `:151-159` (`recompute_stage_only`, confirmed dead/uncalled via grep); `routes/customers.py:83-84,94-95` (hold/release: `touch`+recompute `already_touched=True`); `routes/promises.py:66-67` (promise-create: `touch`+recompute `already_touched=True`) and `:130,143` (promise-evaluate: recompute WITHOUT `already_touched` — cascade off the promise entity); `routes/writeoffs.py:94-95` (approval: `touch`+recompute `already_touched=True`); cascade-only sites `routes/disputes.py:21-24` + callers `:64,120,135,159,174`, `routes/payments.py:116,251`, `routes/invoices.py:38,60` (all recompute WITHOUT `already_touched` — customer's sole change is the cascade); `routes/dunning.py:190-192` (single `touch(customer)` for CURRENT→DUNNING, no recompute).
- **(c) Wording adjustment:** Used "directly mutates that customer" rather than "sets a customer field" so promise-create (whose own customer mutation is the OCC-serialized create, not a plain field set) is covered, keeping §2.6 consistent with §2.9/§3.5. Added the explicit second sentence carving out cascade-only sites (invoice/payment/dispute → customer, and promise-evaluate) so the wording does not narrow those paths to zero increments — there the recompute remains the one increment.

## Step 9: Complete PRD — 2026-06-05T00:00:00.000Z

No structural changes — all headers and table rows are identical; every edit was an in-paragraph insert or revision. The task is complete.

## Summary

Produced `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0160_accounts_receivable_collections/workspace/PRD_COMPLETED.md` by copying `PRD_FINALIZED.md` and applying 15 in-paragraph edits. No new sections, headers, or table rows were added (28 headers and 69 table rows unchanged).

**Counts**
- Source `PRD_FINALIZED.md`: 274 lines / 46,214 bytes (46,099 chars)
- `PRD_COMPLETED.md`: 274 lines / 54,125 bytes (53,981 chars); char delta **+7,882**
- Ambiguity-pins: **9** · Mismatch-revisions: **6**

**Changes** (`{section} — {kind} — {type} — {what} — {impl ref}`)
- §2.1 — revise — ambiguity — unrecognized/blank `X-User-Role` is malformed → `ERR_UNAUTHENTICATED` (401), not 403 — `middleware.py:29-32`
- §2.3 — insert — ambiguity — list tie-break is `id` ascending; pinned `has_more` formula — `customers.py:71`, `response.py:50`
- §2.6 — insert — ambiguity — full deterministic `collection_stage` recompute rule (WRITEOFF / worst-bucket / unredeemed-broken-promise) — `domain.py:111-132`
- §2.7 — insert — ambiguity — broken-promise WATCH floor sits between watch-threshold and GOOD — `domain.py:106-107`
- §3.3 (apply) — revise — ambiguity — target invoice must be OPEN/PARTIAL else `ERR_INVALID_STATE` — `payments.py:135-136`
- §3.3 (reverse) — revise — mismatch — reversal restores `applied_cents` + `short_pay_cents`; status revert keyed to `balance >= face_amount`; nested-ownership and already-reversed guards; cascades `collection_stage` — `payments.py:215-251`
- §3.4 (create) — revise — mismatch — dispute amount *accumulates* onto `disputed_amount_cents` (not "set"); DISPUTED when accumulated == balance — `disputes.py:54-61`
- §3.4 (resolve) — revise — ambiguity — `resolve_credit_cents` ≥ 0; over-amount → `ERR_VALIDATION`; partial credit moves a DISPUTED invoice back to OPEN/PARTIAL; start-review state guard — `disputes.py:88-121`
- §3.4 (reject/withdraw/reopen) — revise — mismatch — full-balance disputes return to OPEN *or* PARTIAL; withdraw role note; reopen resets credit + re-accumulates + re-enters DISPUTED; per-op `ERR_INVALID_STATE` guards — `disputes.py:124-190`
- §3.5 (evaluate) — insert — ambiguity — not-yet-due ACTIVE evaluate is a 200 no-op; recompute `applied_payment_cents` before judging; sticky break-WATCH — `promises.py:122-144`
- §3.6 (approve) — insert — ambiguity — already-approved / non-OPEN-PARTIAL → `ERR_INVALID_STATE`; pinned check order — `writeoffs.py:66-81`
- §3.7 (sequence) — revise — ambiguity — channel enum members; `dunning_stage_index` = 1-based step position; step-validation error codes — `dunning.py:18,38-57,185`
- §3.7 (run) — revise — mismatch — left-to-right existence; DISPUTED suspended; pause suppresses the whole run; highest-step selection; advances `dunning_stage_index` to 1-based step_index; HTTP 201 + array body — `dunning.py:139-195`
- §3.8 (statement) — insert — ambiguity — period bounds (prior `period_end` exclusive → this inclusive); opening = prior snapshot (0 if none); payments-in-period bounds — `statements.py:33-74`
- §3.9 (forecast) — revise — ambiguity — query params; missing/invalid validation split (`ERR_VALIDATION` vs `ERR_INVALID_ENUM`); response echoes `customer_id`/`horizon_days`/`method` + `id`/`created_at` — `statements.py:101-186`
- §3.10 — insert — ambiguity — type/missing errors → `ERR_INVALID_REQUEST`; value-constraint violations (below-min, date/window/horizon, over-credit) → `ERR_VALIDATION` — `common.py:63-102`
- §4 — revise — mismatch — manual apply and dunning run return **201** (not 200); auto-apply returns 200 — `payments.py:156`, `dunning.py:194-195`

Tests were used only as auxiliary cross-reference (e.g., they confirm `step_index==1`, application 201, forecast `method` echo); the implementation was the sole alignment authority.
