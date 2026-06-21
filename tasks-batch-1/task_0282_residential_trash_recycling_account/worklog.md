# Worklog — task_0282_residential_trash_recycling_account

## Step 1: Create task directory — 2026-06-10T11:43:31.000Z

Created `tasks/task_0282_residential_trash_recycling_account/` with `workspace/` subdirectory (pre-assigned reserved index 0282; did not re-scan ./tasks/). Verified `./INSTRUCTION.md` exists at project root.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-10T12:06:58.000Z

Generated all three scaffold artifacts for **task_0282_residential_trash_recycling_account** at **Expert** difficulty. `scaffold_lint.py` returns **VERDICT: clean lint** (46 endpoints, 12 entities, 18 §1.8 instances, 34 active §1.9 instances, 398 calls scanned).

**Complexity profile:** Ledger-reconciliation (primary) + Temporal-windowing (secondary); layers = dual-variant calculation, cascading side effects, rate/threshold triggers, derived-field reconciliation, optimistic concurrency. Flat topology, parallel state-machine shape, peer roles, immediate consistency.

**Entities (12):** ServicePlan, ServiceAccount, CollectionZone, Holiday (immutable, `common_fields:false`), CartAssignment, PickupSchedule, PickupEvent, ExtraPickupRequest, Invoice, Payment, MissedPickupCredit, ContaminationNotice. Self-referential FK on ServiceAccount (`transferred_from_account_id`) for the move/transfer flow; computed fields `account_balance_cents`, `credit_balance_cents`, `is_extra`, `effective_pickup_date`.

**State machines (6):** ServiceAccount carries two parallel dimensions — service `status` (PENDING_START→ACTIVE↔SUSPENDED→STOPPED/TRANSFERRED_OUT) and `billing_status` (CURRENT↔PAST_DUE→IN_COLLECTIONS, system/clock-driven); plus ExtraPickupRequest, PickupSchedule (MISSED→credit, CONTAMINATED→notice cascades), ContaminationNotice (branching OPEN→ACKNOWLEDGED/WAIVED), Invoice (OPEN/PAST_DUE→PAID, OPEN→VOID with credit-restore).

**Calculations (6):** `invoice_gross` (dual-variant provisional vs void-restore, pinned eval order gross→credit→due), `account_balance`, `extra_pickup_charge` (dual-variant frozen-vs-reversed, conditional FREE_BULK_ALLOWANCE branch), `missed_credit` (90-day repeat-escalation threshold, strictly `>2`), `contamination_fee` (first-free warning, MAJOR doubles MINOR), `holiday_shift` (single-day slip, no ripple). All literal asserts computed in code.

**Validations (15, priority-ordered):** auth→authz→existence→reference→body→OCC→state→business (carts-incomplete, plan-archived, address-in-use, date-double-booked, report-too-early, contamination-not-recycling, no-payment-method, payment-amount-mismatch).

**Concurrency (2 OCC rules):** invoice-generate and transfer-out, both on ServiceAccount.version (412).

**Errors (15):** all referenced by a validation/concurrency rule (dropped a redundant ERR_VALIDATION). **Roles (3):** Dispatcher (opaque), AccountHolder (entity_backed:ServiceAccount), CrewLead (opaque).

**Difficulty design (§1.8):** all 9 rules × exactly 2 instances (18 total), each with distinct entity-domain/error-pair/interval-semantic/conserved-quantity differentiation per §0.5. **Corner design (§1.9):** 38 instances (34 active + 4 `excluded_because:` stubs cross-referencing named §1.8 instances) across all nine claim-extraction-guide sections. Instance names unique across both files. Added a `stream`/`status` filter to `GET /accounts/{id}/pickup-schedules` and a `GET /credits/{id}` endpoint during the §1.5 audit to make schedule-row indexing deterministic and satisfy FK reverse-reachability. No forbidden concurrency vocabulary present.

## Step 3: Copy INSTRUCTION.md — 2026-06-10T12:07:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-10T12:13:51.000Z

PRD generated at `workspace/PRD.md` (~277 lines, 41KB). All three Hard Contracts pass.

**Section structure:** §1 Introduction (reconciliation angle, parallel service/billing dimensions, integer-cents). §2 Global Specifications (9 subsections: RBAC+identity translation, response structure, pagination, common properties & versioning with Holiday flagged `common_fields:false`, nested retrieval & reference integrity, validation order priority chain, money & precision, OCC, hierarchical consistency & cascades). §3 Business Logic (13 subsections by lifecycle: provisioning, account+carts, service lifecycle, transfer-out, payment/autopay, schedule+holiday shift, curb outcomes, missed credits, contamination, extra/bulk pickups, period invoicing+gross calc, pay/void, billing dimension+clock). §4 endpoint table (4-col). §5 error table (2-col).

**Coverage:** 12 entities, 46 endpoints, 6 state machines (2 parallel on ServiceAccount: service status + billing_status, plus ExtraPickupRequest, PickupSchedule, ContaminationNotice, Invoice), 6 calculations (invoice_gross, account_balance, extra_pickup_charge, missed_credit, contamination_fee, holiday_shift), 15 validations, 15 error codes, 2 OCC rules.

**Hard Contracts:** Field coverage 61/61 present (PASS); Rule coverage — full validation chain in §2.6, 2 OCC expressed, all 6 state machines' transitions+side effects, 6 calculations fully expressed with constants embedded (300/200/150, >2, 1500×2=3000, free-first, 2-cart floor, 2-item allowance, min/floor, oldest-first tiebreak, +1-day no-ripple) (PASS); Path purity §3 — 384 backtick tokens scanned, 0 path/method tokens (PASS).

**Notable scattering:** OCC `expected_account_version` mechanism in §2.8 but field appearances surface in transfer-out (§3.4) and invoicing (§3.11); validation priority order stated as single chain in §2.6, separated from per-error trigger conditions scattered across §3; calculation constants never tabulated (cart-provisioning floor in §3.11, free-bulk-allowance branch in §3.10, stream credits + 90-day half-open repeat window in §3.8, contamination fee escalation in §3.9); transfer-vs-stop credit divergence (migrate vs expire) split across §3.3/§3.4; void-restore credit conservation in §3.12.

## Step 5: Generate unit tests — 2026-06-10T12:28:38.000Z

Generated complete test infrastructure for **task_0282_residential_trash_recycling_account**.

**Test files:** 7 (`test_01`–`test_07`) plus `conftest.py`, **70 tests total**.
- test_01_entities_and_rbac.py (13)
- test_02_validations_and_precedence.py (17)
- test_03_account_lifecycle.py (10)
- test_04_extra_pickup_charges.py (6)
- test_05_invoice_gross_and_credits.py (8)
- test_06_credit_and_contamination_amounts.py (5)
- test_07_curb_reporting_and_schedules.py (11)

**Queue A (Difficulty, §1.8):** 18 instances, **all 18 translated**, each with ≥2 tests (36 tests). 0 skipped — every difficulty instance had verbatim PRD coverage and uniquely-derivable outcomes (gross/credit math, extra-pickup charge branches, parallel state dimensions, stop/void cascades, repeat-miss and zero-bulk boundaries, cross-entity SUSPENDED guards, double-booking/address-window overlaps, void/waive conservation invariants, and validation-order precedence pairs). The 6 single-failure-assertion instances (precedence pairs, cross-entity-state, resource-overlap) each got a PRD-derivable complement test (success/alternate-branch) to satisfy the ≥2 rule.

**Queue B (Corner, §1.9):** 38 instances = 34 non-stub + 4 stubs. **All 34 non-stub instances translated** (1 test each). **0 skipped.** The 4 `excluded_because:` stubs were correctly NOT translated (cross-references all resolve to real §1.8 instances).

**Skips:** none in either queue — every instance passed the PRD-first two-condition filter.

**test_helpers modules (9):** `__init__.py`, `types.py`, `api_client.py` (50 endpoint methods), `api_errors.py` (15 error IDs registered), `assertions.py` (per-entity + Holiday immutability), `factories.py`, `constants.py`, `test_users.py` (opaque Dispatcher/CrewLead + entity_backed AccountHolder builder), `fixtures.py` (composite setup helpers).

**Verification:** all files byte-compile; 70 tests collect cleanly; all 18 difficulty instances ≥2 tests and all 34 non-stub corner instances ≥1 test; no tag points to nonexistent instance; no skip/skipif/xfail markers; all 98 docstring PRD citations confirmed verbatim against PRD.md.

**Note for downstream:** the design-index CONTAMINATED event payloads omit `severity`, but PRD §3.9 states the crew reports severity as MINOR/MAJOR and the asserted fee of 3000 (MAJOR) is only derivable if severity is an event input. The fixtures therefore send `severity` on contamination event reports, faithful to PRD prose.

## Step 6: Generate implementation — 2026-06-10T12:28:38.000Z

Generated complete Python + Flask implementation under `workspace/implementation/`. All flows verified against a running server.

**Module/file list:** `start.sh` (executable launcher), `requirements.txt` (flask==3.0.3), `app.py` (factory + handlers + routes + `app.run(host=0.0.0.0, port=$PORT, threaded=True)`), `clock.py` (logical server clock, settable via `/_clock/set_current_utc`), `util.py`, `errors.py` (ApiError + error-id→HTTP-status catalog), `response.py` (envelope helpers), `db.py` (in-memory dicts + monotonic tie-break sequence), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `routes/` (helpers, plans_zones, accounts, carts, lifecycle, invoices, schedules, extras, credits_notices, clock_route), `services/` (common, validate, calc, schedule, billing, serialize, lookup).

**start.sh:** `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded install (`if ! python3 -c "import flask"` → pip install), then `exec python3 app.py`. app.py reads `$PORT` (default 10000), binds 0.0.0.0, foreground.

**Storage:** in-memory only — module-level dicts in db.py keyed by UUID. Nothing seeded/preloaded; fresh boot returns total_count 0 everywhere.

**Notable design decisions:**
- Parallel state machines on ServiceAccount: service status (PENDING_START→ACTIVE→SUSPENDED→STOPPED/TRANSFERRED_OUT) + billing_status (CURRENT↔PAST_DUE→IN_COLLECTIONS) tracked independently.
- Calculations (integer cents, no floats): invoice_gross in pinned order base + extra-cart-surcharge + scheduled/completed extra-pickup charges in [period_start, period_end) + OPEN/ACKNOWLEDGED contamination fees traced event→schedule into period; credit_applied = min(gross, credit_balance) frozen, consuming ISSUED credits oldest-first (created_at ASC, smaller-amount tie-break); amount_due = max(0, gross−applied). extra_pickup_charge with 2-item free allowance. missed_credit per-stream (TRASH 300/RECYCLING 200) +150 escalation when prior ISSUED/APPLIED misses in half-open (clock−90d, clock] strictly > 2. contamination_fee first-ever-free, then MINOR 1500 / MAJOR 3000.
- Holiday shift: exact date match only, single-day DELAY_ONE_DAY, no ripple; exposed as effective_pickup_date.
- OCC: expected_account_version required on /accounts/{id}/invoices and /accounts/{id}/transfer-out; mismatch → ERR_STALE_VERSION (412), no mutation.
- Cascades bump child version/updated_at: missed→issue credit; contaminated→open notice; stop→cancel schedules, remove carts, EXPIRE credits; transfer→migrate ISSUED credits, cancel schedules, remove carts; void→restore consumed credits to ISSUED.
- Validation order per PRD §2.6 (auth→forbidden→path-404→body-ref-404→well-formedness→OCC→state→business); body-FK existence before well-formedness for present-and-string FK fields.
- AccountHolder ownership: account-referencing resources gated so X-User-ID == resource's account FK (else ERR_FORBIDDEN); Dispatcher/CrewLead opaque, bypass.
- Holiday lone resource without updated_at/version (id + created_at only).
- Flagged: contamination severity required for CONTAMINATED outcome though events input list is [outcome, reported_at]; read from request body + validated (priority-5) before state/stream checks, faithful to PRD §3.9.

## Step 7: Run tests and iterate — 2026-06-10T12:45:47.000Z

Final state: **all 8 parallel rounds 70/70 passing**, flakiness eliminated. Verified via 3 independent clean 8-round sweeps after the transport fix (2 by the fix subagent + 1 orchestrator-owned confirmation).

### Iteration 7a (initial diagnostic + logic/format fixes)

**Iterations run:** 2 (initial diagnostic sweep + 1 fix iteration). Initial state: deterministic 3 failures in every round (67/70).

**Tests deleted:** None. All three failing tests passed STEP 1 coverage + unique-derivability.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**
- `test_02_validations_and_precedence.py` — `test_contaminated_on_trash_schedule_rejected`: added `"severity": "MINOR"` to the CONTAMINATED report payload. PRD §3.9 ("The crew reports the severity as MINOR or MAJOR") makes severity a required field; per §2.6 validation order, body well-formedness (`ERR_INVALID_REQUEST`, priority 5) precedes the contamination-stream business rule (`ERR_CONTAMINATION_NOT_RECYCLING`, priority 13). Original payload omitted severity, so the PRD-faithful impl correctly returned `ERR_INVALID_REQUEST` first. (STEP 2 test-bug fix — payload made more PRD-faithful.)
- `test_06_credit_and_contamination_amounts.py` — `test_fourth_miss_escalates_to_450`: added `set_clock(rows[3]["effective_pickup_date"])` before reporting the four misses (and imported `set_clock`). The fixture activated at clock 2026-03-02 but the four Monday pickups fall on 03-02/09/16/23; reporting them while clock stayed at 03-02 placed three of four `reported_at` instants after the clock, so PRD §3.8's rolling window `(clock-90d, clock]` correctly excluded them. Advancing the clock to the last pickup's date puts all four within the window, yielding PRD-required 450. (STEP 2 test-bug fix — impl window faithful to PRD; test clock setup was inconsistent.)

**Fixes applied to `implementation/`:**
- `util.py` — added `format_date(dt)` rendering UTC-midnight dates as `YYYY-MM-DDTHH:MM:SSZ` (no fractional seconds). PRD §2.4 reserves the three-fractional-digit form for `created_at`/`updated_at` timestamps, while §3.1/§3.6/§3.10/§3.11 call date fields a "UTC-midnight date" — a distinct category.
- Switched all date-field rendering from `format_ts` (`.000Z`) to `format_date` (`Z`): `services/schedule.py` `_fmt_midnight` (`service_date`, `effective_pickup_date`); `routes/plans_zones.py` (`holiday_date`); `routes/extras.py` (`requested_date`); `routes/invoices.py` (`period_start`, `period_end`, `due_date`); `routes/lifecycle.py` (`service_start_date`). Fixed `test_pickup_on_holiday_slips_one_day`. `reported_at`/`current_utc` left as `format_ts` (PRD §3.7/§3.13 classify them as timestamps).

### Iteration 7b (flakiness elimination — surfaced by orchestrator re-run)

Iteration 7a's subagent exited on a lucky 8/8 sweep, but the orchestrator's independent 8-round re-run surfaced flakiness: rounds 3,6,7 each failed `test_stop_cancels_schedules_and_expires_credits` with `ConnectionError: ('Connection aborted.', BadStatusLine('POST /accounts/<id>/carts ...'))` during fixture setup. A second long-lived subagent diagnosed and fixed it.

**Root cause:** The implementation served HTTP via the Werkzeug development server (`app.run(..., threaded=True)`). Werkzeug's dev server mishandles HTTP keep-alive connection-reuse: the harness's pooled `requests.Session` reused an idle TCP connection that the dev server had already closed server-side, yielding an empty/partial response with no valid HTTP status line. Under the 8× concurrent sweep (8 servers + 8 pytest processes) the race window widened, so the setup `POST /accounts/{id}/carts` intermittently hit the closed-connection window. Pure transport/serving-layer race, not a PRD-logic bug.

**Fixes applied to `implementation/`:**
- `app.py` — replaced the Werkzeug dev server in `__main__` with the production-grade pure-Python WSGI server **waitress** (`from waitress import serve; serve(app, host="0.0.0.0", port=port, threads=8)`). Waitress manages the keep-alive connection lifecycle correctly, removing the race. `$PORT` reading / 0.0.0.0 / foreground preserved; storage stays in-memory only (clean boot per `start.sh`).
- `requirements.txt` — added `waitress==3.0.0`.
- `start.sh` — extended the guarded-install check from `import flask` to `import flask, waitress` so the non-contending guarded install still triggers when waitress is missing.

**Tests deleted / test_helpers / test_suite fixes in 7b:** None — transport-layer issue; the test and its PRD §3.3 stop-cascade assertion remain faithful and intact.

**Confirmation:** 2 consecutive clean 8-round sweeps by the fix subagent + 1 orchestrator-owned confirmation sweep, all rounds 70/70. `results.{1..8}.json` from the final orchestrator sweep persist in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-06-10T12:50:29.000Z

Produced `workspace/PRD_FINALIZED.md`. Line counts: PRD.md = 277, PRD_FINALIZED.md = 279 (+2 lines, +0.72%). Bytes 41424 → 42151 (+727, +1.75%).

**Changes (one edit):**
- §2.4 Common Resource Properties and Versioning — *insert* — Added one sentence pinning JSON serialization of date-valued vs instant-valued fields. Three-fractional-digit form (`YYYY-MM-DDTHH:MM:SS.sssZ`) reserved for instant-valued fields (`created_at`, `updated_at`, `reported_at`, `current_utc`, `api_request_timestamp`); the eight "UTC-midnight date" fields (`holiday_date`, `service_date`, `effective_pickup_date`, `requested_date`, `period_start`, `period_end`, `due_date`, `service_start_date`) render as a UTC instant at midnight with no fractional seconds, `YYYY-MM-DDTHH:MM:SSZ` (e.g. `2026-03-02T00:00:00Z`), null rendered as null — `implementation/util.py:36-50` (`format_date`).

**Why only one edit:** The entire Step 7 `implementation/` diff is the introduction of `util.format_date` and the switch of all date-field rendering from `format_ts` (`.000Z`) to `format_date` (`Z`). PRD §2.4 pinned only the timestamp format for created_at/updated_at; it described date fields semantically as "UTC-midnight date" but never specified serialized output form — genuine PRD-silence the impl resolved. Step 7 `test_suite/` items (severity added to contamination payload; clock advanced before reporting four misses) were fixture/test-clock bugs faithful to existing PRD prose (§2.6, §3.9, §3.8) — no PRD edit warranted. The 7b waitress/transport change traces to no PRD behavior — no edit.

**Pre-edit search log (Edit 1):** (a) Subject: serialization format of every date-typed/instant-typed field. (b) Enumerated/read: util.py (format_ts, format_date, iso_now); services/common.py (created_at/updated_at via iso_now→format_ts); services/serialize.py (all serializers; 8 date fields + reported_at); services/schedule.py (_fmt_midnight→format_date for service_date/effective_pickup_date); routes/plans_zones.py (holiday_date), routes/extras.py (requested_date), routes/invoices.py (period_start/period_end/due_date), routes/lifecycle.py + routes/accounts.py (service_start_date, null before activation), routes/schedules.py (reported_at→format_ts), routes/clock_route.py (current_utc→format_ts). Confirmed exactly 8 date fields (format_date) + 5 instant fields (format_ts). (c) Wording adjustments: scoped no-fractional form strictly to the 8 enumerated date fields and explicitly listed reported_at/current_utc under the three-fractional group; added "null rendered as null" (service_start_date null before activation); used "serialized in output" to confine the pin to rendering, not input parsing (parse_dt is lenient).

## Step 9: Complete PRD — 2026-06-10T12:57:09.000Z

Produced `workspace/PRD_COMPLETED.md`. Source PRD_FINALIZED.md (279 lines, 42151 chars) → PRD_COMPLETED.md (279 lines, 43872 chars). Char delta +1721; line count unchanged (all in-paragraph inserts). Counts: **6 ambiguity-pins, 0 mismatch-revisions**.

**Per-change:**
- §3.1 (Provisioning / holidays) — insert — ambiguity — Pinned duplicate-holiday error: a second holiday on same `(zone_id, holiday_date)` rejected with `ERR_INVALID_REQUEST` (422) — `routes/plans_zones.py:120-122`.
- §3.2 (Equipping carts) — insert — ambiguity — Pinned which same-stream cart is the provisioned (non-extra) one: per `cart_type`, earliest-created ACTIVE cart (by created_at, ties by insertion order) has `is_extra` false, later ACTIVE carts of that stream true; REMOVED carts excluded and retain last value — `routes/carts.py:20-34`.
- §3.3 (Activate-start) — insert — ambiguity — Pinned order of three activation conditions: state check, then cart-completeness (`ERR_CARTS_INCOMPLETE`) before plan-archived (`ERR_PLAN_ARCHIVED`); named `ERR_PLAN_ARCHIVED` when only plan archived — `routes/lifecycle.py:41-49`.
- §3.4 (Transfer-out) — insert — ambiguity — Pinned response shape/status: endpoint returns newly minted destination account (not source) as `data`, `201 Created` — `routes/lifecycle.py:182`.
- §3.7 (Reporting outcomes) — insert — ambiguity — Pinned order of two report-time business checks: `ERR_REPORT_TOO_EARLY` (timing) precedes `ERR_CONTAMINATION_NOT_RECYCLING` (stream); noted `severity` required well-formedness (validated in §2.6 pass ahead of both) when outcome CONTAMINATED — `routes/schedules.py:69-90`.
- §3.12 (Paying invoices) — insert — ambiguity — Pinned payment `amount_cents` must be positive integer (≥1); below 1 rejected `ERR_INVALID_REQUEST` (422) in well-formedness pass before exact-settlement `ERR_PAYMENT_AMOUNT_MISMATCH` — `routes/invoices.py:92,99`.

**Left unchanged:** waitress WSGI transport and `/_clock/set_current_utc` harness endpoint produced no edits (clock behavior already pinned in §3.13/§4). Single-clock-advance chaining CURRENT→PAST_DUE→IN_COLLECTIONS left as-is (§3.13 prose describes each transition's trigger independently; impl evaluates sequentially, consistent).

---

## Pipeline complete — 2026-06-10T12:57:09.000Z

All 9 steps finished. Final state: **70/70 tests passing across 8 parallel stability sweeps, zero flakiness** (verified by 3 independent clean sweeps after the waitress transport fix). Difficulty: Expert.

Final task tree under `tasks/task_0282_residential_trash_recycling_account/`:
- `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`
- `worklog.md`
- `test_helpers/` (9 modules), `test_suite/` (7 test files + conftest, 70 tests)
- `workspace/`: `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md` (Step 8), `PRD_COMPLETED.md` (Step 9), `implementation/` (Flask + waitress, in-memory, `results.{1..8}.json` all 70/70)
