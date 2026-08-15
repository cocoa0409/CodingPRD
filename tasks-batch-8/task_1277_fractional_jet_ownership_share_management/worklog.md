# Worklog — task_1277_fractional_jet_ownership_share_management

## Step 1: Create Task Directory — 2026-08-12T19:03:00.000Z

Task directory `tasks/task_1277_fractional_jet_ownership_share_management/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking command. Treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold Artifacts — 2026-08-12T19:34:00.000Z

Generated SCAFFOLD.yaml (13 entities, 8 state machines, 8 calculations, 13 validation priorities, 65 endpoints, 24 error codes, 4 roles, 2 OCC concurrency rules), SCAFFOLD_DIFFICULTY_DESIGN.yaml (18 instances: 2 per Difficulty Rule 1-9), SCAFFOLD_CORNER_DESIGN.yaml (40 instances across all 9 claim-extraction sections). All formula-derived asserts pre-computed as literals via Python execution of the §1.3 formulas. `scaffold_lint.py` verdict: clean lint (575 calls scanned, 0 violations). No sibling task directory was inspected.

## Step 3: Copy Shared Files — 2026-08-12T19:35:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1277_fractional_jet_ownership_share_management/workspace/INSTRUCTION.md`. (RESUME RUN: verified all three scaffold YAML files parse cleanly and are complete — Step 2 kept, not regenerated.)

## Step 4: Generate PRD — 2026-08-12T19:58:00.000Z

All three hard contracts verified mechanically. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1277_fractional_jet_ownership_share_management/workspace/PRD.md` (348 lines), ending at §5 with no audit footer.

**What was generated**

- **§1 Introduction** — 2 paragraphs, business-context angle (share economics, interchange billing, fiduciary allocation, deterministic clock).
- **§2 Global Specifications** — 10 subsections: RBAC with per-role identity semantics (Owner entity-backed; ProgramAdmin/FleetOps/FinanceOps opaque, with the FinanceOps valuer/approver distinction called out), verbatim §2.2 response envelope, pagination (limit default 10 / min 1 / max 100, offset 0, `created_at` ascending, meta fields), logical clock (startup default 2026-08-01T00:00:00Z, sweeps, contract-year rollover with no carryover), common resource properties (append-only FlightLeg/InvoiceLine/DepreciationSchedule carry only `id` + `created_at`), cents/half-up rounding discipline with pinned per-line rounding, the three OCC write paths with exact error IDs and HTTP 412, a 13-stage validation pipeline preserving scaffold priority order, program posture machine, and owner standing/deposit machine.
- **§3 Business Logic** — 9 subsections organized by lifecycle (program setup → shares/entitlement → booking gate → assignment/interchange → completion/reconciliation → invoicing/dispute loop → maintenance allocation → resale market → exit/buyout/settlement). All 8 calculations rendered as reconstruction-safe prose (800-hour full share, 72/168-hour notice tiers with exact-boundary landing, 1500 bp peak surcharge, min-capped upgrade multiplier, floor-plus-remainder maintenance waterfall with usage-weighted unscheduled variant, pinned depreciation evaluation order, 8200 bp residual / 2000 bp penalty / 3-year hold buyout formula).
- **§4 Endpoint table** — 4 columns, all 65 endpoints, plus status-code paragraph (201 for creations including flight completion and share exit; 200 for modifications) and a list-filter enumeration.
- **§5 Error catalogue** — 2 columns, all 24 error IDs.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 76 required, 76 present, 0 missing
- endpoints[].request_body/input: 14 required, 14 present, 0 missing
- endpoints[].query_params: all filter names present (covered via entity fields + §4 filter paragraph), 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 13 checked, 13 expressed in ordered §2.8 pipeline prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected field + error_id + 412 named; listing-create share OCC also covered), 0 missing
- state_machines[].transitions: 36 checked across 8 machines, 36 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (constants, boundaries, pinned orders, variants), 0 missing
- validations[] conditions: 13 checked, 13 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in §2.9/§2.10/§3 narratives, 0 missing
- entities[].fields[] structured content: defaults/initials/immutability reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (upgrade/downgrade, straight-line/double-declining, scheduled/unscheduled allocation, dispute resolve branches, exit reject/withdraw, tier boundaries), 6 with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 296
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additionally verified: §2.2 matches `section-2.2-response-structure.md` byte-for-byte (including `req_RANDOMALPHANUM123456` and the empty `"data": { }`), all 51 state/enum values appear backticked, all 24 error IDs appear in §2/§3 prose, and the withheld difficulty/corner design files were never opened.

## Step 6: Generate Implementation — 2026-08-12T20:10:00.000Z

All implementation files in place. Final report.

## Summary

Generated a complete Python + Flask implementation for task 1277 (Fractional Jet Ownership & Share Management) at `/home/ubuntu/github/CodingPRD/tasks/task_1277_fractional_jet_ownership_share_management/workspace/implementation/`.

### Files produced
- `start.sh` — foreground bash launcher; guarded `pip install` (only when `flask` missing); `exec python3 app.py` listening on `0.0.0.0:$PORT` (default 10000).
- `requirements.txt` — `flask>=3.0,<4`.
- `app.py` — Flask entry point with `ApiError` handler and 404/405 mapping to the error envelope.
- `clock.py` — Logical clock pinned at startup to `2026-08-01T00:00:00Z`, advanced only via `POST /_clock/set_current_utc`.
- `db.py` — Empty in-memory stores keyed by id; no seeding anywhere.
- `errors.py`, `response.py`, `middleware.py`, `util.py` — envelope (`meta`/`response_type`/`data`), error IDs, `X-User-ID`/`X-User-Role` auth, pagination (`limit`/`offset`, 10/1/100/0), `Decimal`-based cents/hours rounding (ROUND_HALF_UP).
- `services/core.py` — record constructors, per-entity serializers (FlightLeg/InvoiceLine/DepreciationSchedule omit `updated_at`/`version`), owner-standing recompute, and `clock_advance()` sweeping booking expiry, 180-day listing expiry, 30-day invoice `PAST_DUE` aging, and contract-year rollover.
- `routes/` — one blueprint per resource: `clock`, `programs` (suspend/resume/wind-down/close with `ERR_PROGRAM_NOT_CLOSABLE` preconditions and owner-exit cascade), `classes`, `aircraft`, `owners` (suspend/reinstate), `shares` (create with `ERR_INVALID_FRACTION`, activate computing entitlement = fraction × 800, exit opening), `bookings` (create with `expected_share_version` OCC, confirm with full validation pipeline — posture → standing → temporal → entitlement `>=` boundary — freezing `notice_tier`; assign with half-open window conflict and upgrade/downgrade direction; cancel with compensating re-credit; complete creating FlightLeg with `peak_day_flag`, reconciling `hours_remaining_cy += estimated − actual` allowing overdraft; quote; suggest-aircraft ranked by |Δseats|, hours flown, created_at), `invoices` (open with `ERR_DUPLICATE_INVOICE_PERIOD`; issue running management-fee, occupied-hours, peak 1500bp, interchange adjustment with owner-friendly `min(fly_rate, round(req_rate × bp/10000))` cap, maintenance allocation, December depreciation pass-through with pinned compute-then-update order; pay with exactness; dispute/resolve loop), `listings` (OCC on both share and listing versions, self-dealing rejection, close-sale rebasing depreciation), `maintenance` (start with `ERR_MAINTENANCE_OVERLAP`, overlapping CONFIRMED bookings unassigned; complete with `override_early` and waterfall allocation — floor + deterministic remainder distribution by weight DESC, owner created_at ASC), `exits` (value with buyout formula — 8200bp market value, 2000bp early-exit scaled by unelapsed fraction of 3-year hold; segregation-of-duties approve via `_valued_by`; settle netting outstanding invoices and deposit, force-closing invoices, closing share, transitioning owner to EXITED).

### Verified behavior via live smoke tests
- Boot from fresh process succeeds and serves HTTP within seconds.
- Program → class → tail → owner → share → activate (entitlement = 50.00 for 1/16).
- Booking lifecycle: OCC stale version → `ERR_STALE_SHARE_VERSION` (412); 60h on 50h balance → `ERR_ENTITLEMENT_EXHAUSTED` (422); past departure → `ERR_TEMPORAL_INVALID` (422); bad fraction → `ERR_INVALID_FRACTION` (422).
- Confirm → assign → complete: share balance 50 → 45.75 after 3.5h estimate and 4.25h actual; peak-day flag honored.
- Invoice aggregation for 2026-08: management 62,500 + occupied 2,125,000 + peak 318,750 = 2,506,250 total (per-line rounding).
- Contract-year rollover: clock crossing 2027-01-01 bumps `contract_year_index` to 1 and resets `hours_remaining_cy` to 50.00.
- Resale: listing → accept (OCC on listing version) → close-sale rebases depreciation basis to final price.
- Exit: value computes market 82,000,000, penalty 16,400,000, buyout 65,600,000; same-user approve → `ERR_SEGREGATION_OF_DUTIES`; settlement = 65,600,000 + 5,000,000 deposit = 70,600,000 (fixed a double-subtraction of penalty during validation); share → CLOSED, owner → EXITED, deposit → 0.

## Step 5: Generate Unit Tests — 2026-08-12T20:24:00.000Z

Done. Complete test infrastructure generated for task 1277.

## What was produced

**`test_helpers/`** (9 files, Stage 1):
- `types.py` — 14 status enums + 13 entity TypedDicts; `FlightLeg`/`InvoiceLine`/`DepreciationSchedule` correctly modeled as append-only (no `updated_at`/`version`, per PRD §2.5).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (50 methods, incl. `/_clock/set_current_utc`).
- `api_errors.py` — all 24 error IDs + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py`, `factories.py`, `constants.py` (FULL_SHARE_HOURS=800, PEAK_SURCHARGE_BP=1500, MARKET_VALUE_BP=8200, EARLY_EXIT_BP=2000, MIN_HOLD_YEARS=3, tier thresholds, 30-day aging).
- `test_users.py` — opaque operator constants + `make_owner_headers(owner_id)` (entity-backed) and `make_finance_ops_headers(id)` for segregation-of-duties flows.
- `fixtures.py` — composite builders: scenario setup (program+class+owner+ACTIVE share), booking lifecycle chains (confirm/assign/complete), issued-invoice, delinquent-owner (PAST_DUE sweep), transfer listing, maintenance, and exit-to-SETTLED flows with distinct FinanceOps identities.

**`test_suite/`** — `conftest.py` + 10 test files, **75 test functions (77 collected items)**.

## Coverage audit (automated, against both YAMLs)
- Queue A: all 18 difficulty instances have ≥2 tagged tests (one has 3).
- Queue B: all non-stub corner instances have ≥1 tagged test, except two deliberate skips (below). All 8 `excluded_because` stubs left untranslated; every stub's `difficulty_instance` pointer resolves.
- Every docstring: verbatim PRD quote (all 75 passed a normalized-substring grep of PRD.md) + exactly one `Design:` tag as the last line. No skip/xfail markers. Everything byte-compiles; pytest collection succeeds.

## PRD-first adjudications (gaps and corrections)
1. **SKIPPED** `Corner/state_machines/share_activation_blocked_in_suspended_program` — PRD §2.8 stage 5 enumerates the posture gate for booking create/confirm and listing create/accept only; no error_id is named for share activation under SUSPENDED (a reader could answer ERR_INVALID_STATE). Not uniquely derivable.
2. **SKIPPED** `Corner/cross_cutting_layers/rate_threshold_past_due_exactly_30_days` — PRD says PAST_DUE "when the clock *passes* thirty days after `issued_at`"; at exactly +30d, `>=` vs `>` is ambiguous. The difficulty instance covers the sweep safely at +31d.
3. **Corrected literal** in `Corner/consistency_model/completion_effects_visible_immediately` — the design's precomputed 199.50 contradicts the PRD §3.5 formula; PRD uniquely derives 197.50 (200.00 − 2.00 confirm debit, then +2.00 − 2.50 reconciliation). Asserted 197.50.
4. **Corrected fixture** for `Difficulty/cross_entity_state_dependency/program_close_gated_by_invoice_states` — the design's own chain settles the exit after disputing the invoice, but §3.9 settle force-closes that owner's DISPUTED invoice, self-neutralizing the blocker. I moved the blocking DISPUTED invoice to a second owner, preserving the asserted claim (close gated by invoice state).
5. **Relaxed error identity** in `Difficulty/priority_pair_validation_conflict/confirm_state_vs_fiscal_priority` — PRD stage 4 allows ERR_INVALID_STATE or ERR_ALREADY_TERMINAL on a CANCELLED booking, so the test uses `validate_error_is_one_of` + HTTP 409, still asserting the priority claim (state stage masks the fiscal 422).

## Step 7: Run Tests and Iterate — 2026-08-12T20:45:00.000Z

All 8 rounds pass 77/77. Clean sweep achieved.

## Summary

- **Iterations run**: 2 (first sweep: 23 failing in all 8 rounds; fixes applied; second sweep: 8/8 rounds clean, 77/77 each).

- **Tests deleted**: none.

- **Fixes applied to `test_suite/`** (no test_helpers changes needed):
  - `test_04_assignment_and_interchange.py` — `test_upgrade_billing_capped_below_rack_rate`, `test_downgrade_produces_negative_adjustment_line`: added `set_clock("2026-09-11T00:00:00Z")` after assign, before complete. The tests completed the flight while the logical clock still read 2026-08-01, then invoiced September — but PRD §3.5 stamps `completed_at` from the clock, so the legs correctly aggregated into August, not September.
  - `test_05_completion_and_billing.py` — `test_final_invoice_uses_actuals_plus_peak_surcharge` and the `TestPerLineRoundingOrder._fixture` (driving `test_invoice_total_uses_per_line_rounding`, `test_line_components_rounded_individually`): same clock-precondition fix; the fixture was rewritten to confirm+assign at the August clock, then `set_clock("2026-09-08T00:00:00Z")` before completing both legs (confirm requires departure strictly in the future, so the clock could not be advanced earlier).
  - `test_10_exits_and_program_close.py` — `_valued_exit_after_one_year` fixture: passed `monthly_fee_base_cents=4000000` explicitly. The test's assertions assumed a 4000000 fee base ("1/8 x 4000000 = 500000") but the MID class spec default in `test_helpers/constants.py` is 2500000 (4000000 is HEAVY) — fixture self-inconsistency, not an implementation bug.

- **Fixes applied to `implementation/`**:
  - `services/core.py` — `hours_str`: was rendering hour quantities as strings (`f"{v:.2f}"`, e.g. `"50.00"`); now returns a JSON number quantized half-up to two decimal places per PRD §2.6 ("Hour quantities ... carry exactly two decimal places and round half-up"). This fixed 15 tests asserting numeric hour values via `pytest.approx`.
  - `routes/invoices.py` — `pay_invoice`: was rejecting payment of `PAST_DUE` invoices with `ERR_INVALID_STATE`; now accepts `ISSUED` or `PAST_DUE`. PRD §3.6/§2.10 explicitly contemplate paying a past-due invoice ("A paid invoice moves to `PAID`, and if that clears the owner's last `PAST_DUE` invoice, their standing returns from `DELINQUENT` to `GOOD`"). This fixed `test_paying_last_past_due_invoice_restores_good`.

Orchestrator verification: all 8 `results.{1..8}.json` files independently confirm `passed=77, failed=0, total=77`.

## Step 8: Finalize PRD — 2026-08-12T20:53:00.000Z

Done. PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1277_fractional_jet_ownership_share_management/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts**: PRD.md = 346 lines, PRD_FINALIZED.md = 346 lines (0.0% delta; two sentences revised in place).

**Changes** (one bullet each):
- **§2.6** — revise — appended "and they appear on the wire as JSON numbers, never strings, each being the underlying value quantized half-up to two decimal places" to the hour-quantities sentence, pinning the serialization type the impl fix chose — `implementation/services/core.py:33-40` (`hours_str`).
- **§3.6** — revise — "The owner pays by tendering…" → "The owner pays an invoice standing `ISSUED` or `PAST_DUE` by tendering…", pinning the payable states the impl fix chose — `implementation/routes/invoices.py:353-358` (`pay_invoice`).

**Step-7 items judged not to need PRD edits** (PRD already determined the behavior or pure fixture bugs):
- `test_04` / `test_05` clock-precondition fixes — PRD §3.5 already pins `completed_at` "stamped from the clock" and §3.6 pins aggregation to the month containing `completed_at`; §3.3 pins confirm requiring departure strictly in the future. Tests were violating pinned behavior; no PRD silence.
- `test_10` `_valued_exit_after_one_year` fixture passing `monthly_fee_base_cents=4000000` — fixture self-inconsistency against the test_helpers MID default, not an impl/PRD divergence.

**Pre-edit search log**:
- **Edit 1 (§2.6)** — (a) subject: wire representation of hour quantities. (b) enumerated/read: `services/core.py:33-40` (`hours_str` returns `float(Decimal.quantize(0.01, HALF_UP))`); all six serializer call sites (`aircraft_view:83`, `share_view:112/116`, `booking_view:133`, `flight_leg_view:150`, `invoice_line_view:181`); request-side parsers `as_num` in `util.py:60-63` used by `routes/bookings.py:115-117` (`estimated_block_hours`) and `routes/bookings.py:421` (`actual_block_hours`) — both require JSON numbers, reject strings; quote endpoint (`bookings.py:238-239`) emits cents only; grep for every other `hours` reference confirmed no serializer bypasses `hours_str` (internal storage as float is irrelevant to the wire). (c) Wording chosen says "JSON numbers, never strings… quantized half-up to two decimal places" — covers both request and response direction without claiming the serialized text always shows two trailing digits (Python renders e.g. `50.0`), matching the impl exactly.
- **Edit 2 (§3.6)** — (a) subject: invoice statuses that accept payment. (b) enumerated/read: `routes/invoices.py:346-367` (`pay_invoice`: owner-match check, `PAID`/`SETTLED_AFTER_DISPUTE` → `ERR_ALREADY_TERMINAL`, `OPEN`/`DISPUTED` → `ERR_INVALID_STATE`, accepts exactly `ISSUED`/`PAST_DUE`, then `recompute_owner_standing`); `services/core.py:254-258` (standing restoration); `routes/exits.py:157-164` (settlement force-closes `OPEN`/`ISSUED`/`PAST_DUE`/`DISPUTED` invoices to `PAID` outside the pay endpoint); `dispute`/`resolve-dispute` paths for parallel state-gate behavior. (c) Scoped the clause to "The owner pays…" so it does not constrain the exit-settlement force-close path, and left error-code mapping for non-payable states to the existing §2.8 stage-4 rule rather than asserting per-state codes (impl's `OPEN`/`DISPUTED` → `ERR_INVALID_STATE` and terminal → `ERR_ALREADY_TERMINAL` both remain consistent with that general rule).

## Step 9: Complete PRD — 2026-08-12T21:08:00.000Z

Done. All edits are in `/home/ubuntu/github/CodingPRD/tasks/task_1277_fractional_jet_ownership_share_management/workspace/PRD_COMPLETED.md`.

**Source vs output:** `PRD_FINALIZED.md` 346 lines / 47,105 chars → `PRD_COMPLETED.md` 348 lines / 54,230 chars (char-delta +7,125; 49 diff lines, all inline paragraph edits — no new sections).

**Counts:** 41 ambiguity-pins, 12 mismatch-revisions (some edits bundle multiple pins at one site; bullets below are per edit site).

- §2.1 — insert — ambiguity — failed Owner ownership comparison → `ERR_FORBIDDEN_ROLE` (403), evaluated after resource existence — implementation/routes/bookings.py:125, listings.py:122, invoices.py:350, exits.py:218
- §2.2 — insert — ambiguity — `api_request_timestamp` stamped from the logical clock — implementation/response.py:15
- §2.2 — insert — ambiguity — unknown path/unsupported method → `ERR_NOT_FOUND` (404); unexpected failure → `ERR_INTERNAL` (500) — implementation/app.py:20-30
- §2.3 — insert — ambiguity — non-integer/out-of-range limit/offset → `ERR_INVALID_REQUEST`; `created_at` ties broken by ascending `id`; `has_more` = (offset+limit) < total_count — implementation/util.py:78-111, response.py:29
- §2.4 — insert — ambiguity — unparseable `to_iso8601` → `ERR_INVALID_REQUEST` — implementation/routes/clock.py:21-28
- §2.4 — insert — ambiguity — rollover anniversary fires iff strictly after previous clock reading and at/before new reading — implementation/services/core.py:265-277,316-328
- §2.5 — revise — ambiguity — `created_at`/`updated_at` stamped from logical clock; `version` begins at 1 — implementation/services/core.py:21-30
- §2.8 stage 3 — revise — ambiguity — body-referenced identifiers (not just path) yield `ERR_NOT_FOUND` — implementation/routes/bookings.py:128-130, classes.py:27-29
- §2.8 stage 4 — revise — mismatch — share activation, tail assignment, sale closing, invoice issuance, dispute resolution report `ERR_INVALID_STATE` even for terminal targets (impl only selectively raises `ERR_ALREADY_TERMINAL`) — implementation/routes/shares.py:143, bookings.py:346, listings.py:165, invoices.py:177,394
- §2.8 stage 5 — revise — mismatch — posture gate also applies to share creation, which `SUSPENDED` does not block but `WINDING_DOWN`/`CLOSED` do — implementation/routes/shares.py:76-79
- §2.8 stage 6 — insert — ambiguity — self-dealing check runs immediately before the standing gate on listing acceptance — implementation/routes/listings.py:142-148
- §2.9 — insert — ambiguity — resume precondition violation → `ERR_INVALID_STATE` (409) — implementation/routes/programs.py:91-95
- §2.10 — insert — ambiguity — reinstatement with PAST_DUE invoices → `ERR_INVALID_STATE` (409) — implementation/routes/owners.py:97-99
- §2.10 — revise — mismatch — `EXITED` also reached via program closure, which does not zero deposit balances (only exit settlement draws the ledger to zero) — implementation/routes/programs.py:174-177, exits.py:179-190
- §3.1 — revise — mismatch — `program_code` uniqueness not enforced; `currency` and peak-day entries carried as unvalidated strings; month out of 1–12 / duplicate peak dates → `ERR_INVALID_REQUEST` — implementation/routes/programs.py:22-48
- §3.1 — insert — ambiguity — class constraint violations (non-positive rates/seats, multiplier < 10000, duplicate class_code) → `ERR_INVALID_REQUEST` — implementation/routes/classes.py:40-56
- §3.1 — insert — ambiguity — duplicate tail_number → `ERR_INVALID_REQUEST`; class of another program → `ERR_NOT_FOUND` — implementation/routes/aircraft.py:33-40
- §3.2 — insert — ambiguity — `initial_deposit_cents` must be non-negative (zero allowed), else `ERR_INVALID_REQUEST` — implementation/routes/owners.py:38-41
- §3.2 — insert — ambiguity — non-positive `purchase_price_cents` → `ERR_INVALID_REQUEST`; share creation posture rule; `annual_entitlement_hours`/`hours_remaining_cy` null until activation — implementation/routes/shares.py:71-79,101-102
- §3.2 — insert — ambiguity — unrecognized schedule method/recovery years → `ERR_INVALID_REQUEST`; schedule created at creation only when both fields supplied, otherwise activation creates default `STRAIGHT_LINE`/5-year schedule — implementation/routes/shares.py:81-93,109-110,164-166
- §3.2 — insert — ambiguity — activation gate error codes (`ERR_INVALID_STATE` / `ERR_PROGRAM_POSTURE_BLOCKS` / `ERR_OWNER_STANDING_BLOCKS`) — implementation/routes/shares.py:142-153
- §3.3 — insert — ambiguity — booking creation gates on neither share status nor owner standing; requested class may be any registered class; non-positive estimate → `ERR_INVALID_REQUEST`; finer-precision estimates rounded at intake; `notice_tier` null until confirmation; `interchange_direction` starts `NONE` — implementation/routes/bookings.py:104-170
- §3.3 — insert — ambiguity — quote echoes frozen tier for confirmed bookings, computes against current clock otherwise — implementation/routes/bookings.py:240-242
- §3.3 — insert — ambiguity — confirmation against a non-`ACTIVE` share → `ERR_INVALID_STATE` — implementation/routes/bookings.py:303-305
- §3.4 — insert — ambiguity — non-`IN_SERVICE` tail → `ERR_INVALID_STATE`; no program-membership check on assigned tail; booking window = departure → departure + estimated hours; direction decided by rate comparison alone (cross-class equal rate → `NONE`) — implementation/routes/bookings.py:341-379
- §3.4 — insert — ambiguity — suggestions restricted to the booking's program, final tie-break by `id`, full list returned unpaginated — implementation/routes/bookings.py:255-281
- §3.5 — insert — ambiguity — completion precondition failures → `ERR_INVALID_STATE`; non-positive actuals → `ERR_INVALID_REQUEST` — implementation/routes/bookings.py:421-437
- §3.5 — revise — mismatch — no invoice recalculation at completion (aggregation runs only at issuance) — implementation/routes/bookings.py:476-480
- §3.6 — revise — mismatch — an `OPEN` invoice has no lines and zero totals; lines are computed and persisted at issuance, not accumulated during the month — implementation/routes/invoices.py:92-104,172ff
- §3.6 — revise — mismatch — management fee keyed to share status at the issuance clock (not "spent any part of the period in"), so a share `CLOSED` at issuance contributes nothing — implementation/routes/invoices.py:191-203
- §3.6 — insert — ambiguity — occupied-hours ownership attributed at issuance; `OCCUPIED_HOURS`/`PEAK_SURCHARGE`/`INTERCHANGE_ADJUSTMENT` lines carry the leg's actual hours as `quantity_hours` — implementation/routes/invoices.py:207-252
- §3.6 — insert — ambiguity — maintenance lines drawn from events completed within the period, attributed to the owner's earliest-created qualifying share (null otherwise), zero quantity, no booking — implementation/routes/invoices.py:255-279
- §3.6 — revise — mismatch+ambiguity — straight-line allowance capped at remaining basis; settled-exit `CLOSED` shares skipped; zero allowance posts no line — implementation/routes/invoices.py:281-330
- §3.6 — revise — mismatch — `total_due_cents` is exactly mgmt + occupied + tax (no `applied_credit_cents` exists) — implementation/routes/invoices.py:332-335, services/core.py:157-171
- §3.6 — insert — ambiguity — issuance blocked for `EXITED` owner → `ERR_OWNER_STANDING_BLOCKS`; non-`OPEN` invoice → `ERR_INVALID_STATE` — implementation/routes/invoices.py:176-186
- §3.6 — insert — ambiguity — negative `adjusted_total_cents` → `ERR_INVALID_REQUEST`; `reject_adjustment` takes precedence when both supplied — implementation/routes/invoices.py:396-414
- §3.7 — insert — ambiguity — negative cost → `ERR_INVALID_REQUEST`; `unscheduled_flag` is a mandatory boolean — implementation/routes/maintenance.py:48-62
- §3.7 — insert — ambiguity — maintenance-start unassignment leaves booking `CONFIRMED` and does not reset `interchange_direction` — implementation/routes/maintenance.py:122-133
- §3.7 — insert — ambiguity — `override_early` must be boolean; allocation tie-break adds ascending owner id; zero total weight or zero cost allocates zero to each candidate owner — implementation/routes/maintenance.py:146-153,196-219
- §3.7 — revise — mismatch — deferred allocation is permanent: with no `ACTIVE` owner at completion the cost stays on the event and no line is ever emitted (impl has no re-allocation trigger on activation) — implementation/routes/maintenance.py:163-177
- §3.8 — insert — ambiguity — non-positive ask → `ERR_INVALID_REQUEST`; close-sale requires positive price and `UNDER_OFFER` (`ERR_INVALID_STATE` otherwise); rebase also resets `current_year_allowance_cents` — implementation/routes/listings.py:40-43,164-173,188-191
- §3.8 — revise — mismatch — `program_repurchase_flag` is inert (recorded and echoed; no special repurchase flow) — implementation/routes/listings.py:44,78
- §3.9 — insert — ambiguity — exit on a share not `ACTIVE`/`LISTED` → `ERR_INVALID_STATE`; exits are not posture-gated at all — implementation/routes/shares.py:178-180
- §3.9 — insert — ambiguity — settle of valued-but-unapproved exit → `ERR_INVALID_STATE`; `settlement_cents` null until `SETTLED` — implementation/routes/exits.py:148-153,226
- §3.9 — insert — ambiguity — force-closed invoices land in `PAID`; settlement performs no owner-standing recomputation — implementation/routes/exits.py:158-165
- §4 — revise — mismatch — per-invoice line listing is scoped by the path invoice alone; the four line filters apply only to the cross-invoice listing — implementation/routes/invoices.py:130-156
