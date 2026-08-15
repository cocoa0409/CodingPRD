# Worklog — task_1627_costume_prop_rental_house

## Step 1: Create Task Directory — 2026-08-14T03:10:00.000Z

Task directory `tasks/task_1627_costume_prop_rental_house/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking command; Step 1 treated as DONE per instructions (no index scan, no new directory creation).

## Step 2: Generate Scaffold — 2026-08-14T04:27:00.000Z

All three scaffold artifacts are generated and lint-clean. Final report:

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_1627_costume_prop_rental_house/`)

| File | Contents | Size |
|---|---|---|
| `SCAFFOLD.yaml` | §1.0–§1.7 (no design keys) | 1829 lines |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | `scaffold_difficulty_design:` only — 9 rule groups, 22 instances | 975 lines |
| `SCAFFOLD_CORNER_DESIGN.yaml` | `scaffold_corner_design:` only — 9 sections, 62 instances (55 active + 7 `excluded_because` stubs) | 1440 lines |

## Design summary (harder-than-expert calibration)

- **Complexity profile**: primary archetype `temporal_windowing` + secondary `pricing_engine`; layers = optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers; flat topology, cyclic state machines, segregation-of-duties role model, immediate consistency.
- **Surface**: 14 entities, 63 endpoints, 38 error codes, 12 ordered validation priorities, 10 calculations, 13 state machines, 2 OCC concurrency rules on `Production.version` — well above the Expert band (10–15 entities / 20–32 endpoints / 18–30 errors).
- **Nine difficulty rules**, each with 2–3 grounded instances: dual-variant damage valuation (AGREED_VALUE 60000 vs DEPRECIATED_REPLACEMENT 21600 for identical units, diverging on renter insurance posture) and long-run vs weekly rental variants (8000 vs 10000); combinatorial formulas in modes (a) three-tier quote stacking 10000/8000/7000, (b) pinned per-line rounding (5332, not 5333), (c) pinned payment→balance→outstanding→credit_hold evaluation order; cyclic machines (ItemUnit rental loop, Reservation amend re-quote loop); depth-3 cert-expiry→suspend→release cascade + depth-2 check-in→pull-list auto-close cascade; priority conflicts (state-beats-fiscal, referential-beats-temporal); three boundary metrics (56-day/8-week `>=` threshold, credit-limit strict-`>` equality, cleaning-backlog depth 10); three cross-entity dependency pairs; two interval semantics (inclusive aggregate capacity vs per-unit cleaning-buffer exclusion); two conserved quantities (unit pool across submit+cancel, renter ledger across issue+credit).
- All formula-derived asserts are pre-computed literals (20 formulas verified by executing them in Python); every setup chain replays from empty-DB against §1.5 with full `${var}` closure, literal discipline, and OCC versions referenced from captures.

## Issues caught and fixed during the mandatory replay pass

1. **Invoice sweep over-flagging**: a single `invoiced` flag made late fees unreachable once rental was billed — split into `rental_invoiced` / `late_fee_invoiced` (independent sweep flags), which the credit-ordering difficulty instance depends on.
2. **FULFILLED timing**: submit-level fulfillment made `ERR_RESERVATION_IN_USE` unreachable (release is only valid from CONFIRMED). FULFILLED now happens at dispatch; PICKING pull-list cancel needs no rollback.
3. **Dead error removed**: `ERR_LINES_ALREADY_OUT` was unreachable (lines go OUT only at dispatch, when the list is no longer PICKING); dropped from catalog, machine, validations.
4. **`state_beats_fiscal_on_dispatch` chain rebuilt**: original chain generated an invoice while lines were still PICKED (empty sweep → wrong error); now uses a second production with a dispatched line to create the outstanding balance.
5. Lint-driven fixes: two FK reverse-reachability gaps closed via `rate_card_id?` / `invoice_id?` list filters; YAML flow-mapping quoting for `$.data[N]` captures and bracketed grounds.

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(§1.5 endpoints declared: 63; §1.1 entities: 14; §1.8 instances scanned: 22; §1.9 instances scanned: 55; calls scanned: 1216)

Additional mechanical checks passed: 84 unique instance names across both design files, correct file split (design keys only in their own files), no forbidden concurrency vocabulary, every error in the catalog referenced and covered by at least one instance. Note: the task directory already contained a pre-existing `worklog.md` and `workspace/` directory, which I did not create or modify.

## Step 3: Copy Shared Files — 2026-08-14T03:11:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1627_costume_prop_rental_house/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T04:45:00.000Z

Generated `/home/ubuntu/github/CodingPRD/tasks/task_1627_costume_prop_rental_house/workspace/PRD.md` from the scaffold. The two difficulty-design files were not opened or referenced.

**Document design (domain-derived, not template-copied):**
- **§1** — two paragraphs from the business-context angle (hold-vs-shelf contention, money at every cycle stage), ending on the logical-clock determinism hook.
- **§2** — nine subsections: 2.1 RBAC with per-role `identity:` translations (RenterContact entity-backed to `Renter.id`; the other three opaque with concrete record-field examples), 2.2 emitted byte-identical from `section-2.2-response-structure.md` (verified programmatically), 2.3 pagination, 2.4 logical clock + daily sweep (incl. transitive date advancement and all six response id arrays), 2.5 common resource properties, 2.6 integer-cents/round-half-up with the 2666.4 per-line-vs-sum-round example, 2.7 OCC (`expected_production_version` on reservation + pull-list creation, `ERR_STALE_VERSION` 412, stale-version framing only), 2.8 cascade inventory, 2.9 the full 12-priority validation order.
- **§3** — eight subsections organized along the rental business timeline (renters/insurance → catalog/sourcing/deaccession → rate cards/productions → reservations/quotes → pull lists/selector/dispatch → check-in/restoration/cleaning → claims → invoicing/settlement), with all ten calculations rendered as reconstructible prose (inclusive-day windows, ceil-week pricing, deep-run tiering, per-line rounding pin, 5-year depreciation with 10% salvage floor, strict buffered per-unit exclusion vs inclusive aggregate overlap, rush multiplier at queue depth ≥ 10, pinned invoice/credit evaluation orders) and constants embedded in context.
- **§4** — 63 endpoints, 4-column table; **§5** — 38 errors, 2-column table.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint input/query/path identifiers: 97 required, 97 present, 0 missing
- error IDs: 38 required, 38 present, 0 missing
- enum/state values: 89 required, 89 present, 0 missing
- role names: 4 required, 4 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 12 priorities expressed as an explicit ordered list in §2.9, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (both write endpoints + expected_production_version + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 60 checked (incl. transitive sweep advancement note and submit-vs-dispatch FULFILLED note), 60 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise prose (no pseudocode, no fuzzy quantifiers), 0 missing
- validations[] conditions: all checks matchable to their error_id in §2/§3 narrative, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives (suspension/cancel/deaccession cascades, dispatch fan-out, check-in fan-out, void unbilling, settle bubble-up), 0 missing
- entities[].fields[] structured content: defaults, null-until semantics, and computed-field derivations all placed on owning entities, 0 missing
- sibling-branch symmetry: check-in severity branches, rate variants, valuation methods, invoice payment/credit transitions, and claim dispute loop rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 791
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three contracts PASS. One scaffold nuance handled: the pull-list cancel endpoint description mentions rolling `FULFILLED` reservations back, but the state machine (source of truth) specifies covered reservations stay `CONFIRMED` since fulfillment occurs only at dispatch — the PRD follows the state machine and makes that serialization point explicit.

## Step 5: Generate Unit Tests — 2026-08-14T05:20:00.000Z

Test generation for task_1627 (Costume & Prop Rental House) is complete and fully verified.

## What was generated

**`test_helpers/`** (9 files):
- `types.py` — 12 status/type enums + 16 entity TypedDicts (all entities carry `common_fields: true`, so all include `id`/`created_at`/`updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (clock, ops sweep, renters, certs, rate cards, items, units, productions, reservations, pull lists, lines, fittings, claims, tickets, invoices)
- `api_errors.py` — all 38 error IDs with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assert functions + `parse_iso` helper (used to compare `hold_expires_at` instants without depending on timestamp string formatting)
- `factories.py`, `constants.py` — payload factories; domain constants (insurance minimums, cleaning fees/buffers, multipliers, hold hours, grace days, standard RC-2026 rate card)
- `test_users.py` — shared headers for the three opaque roles; `make_renter_contact_headers(renter_id)` for the entity-backed RenterContact role (threaded through every ownership-gated call in fixtures)
- `fixtures.py` — tiered composite setup: `create_active_renter`, `create_confirmed_production`, OCC-aware `place_reservation`/`create_pull_list_for` (re-reads `Production.version` before each guarded write), `setup_confirmed_reservation_scenario` → `setup_dispatched_scenario` → `setup_checked_in_scenario` → `setup_damaged_line_with_claim` / `setup_issued_invoice_scenario`, plus claim/invoice/ticket helpers

**`test_suite/`** — 99 tests across 9 concern-grouped files + `conftest.py`:
- 44 tests covering all 22 §1.8 difficulty instances (exactly 2 each)
- 55 tests covering all 55 non-stub §1.9 corner instances (1 each); the 7 `excluded_because:` stubs were not translated (verified their difficulty-instance pointers all resolve)

## Verification results

- **Tag audit**: all 99 docstrings end with exactly one `Design: Difficulty/...` or `Design: Corner/...` line as the last line; every tag resolves to a real instance; zero stubs translated; zero untagged tests
- **PRD citation audit**: every docstring carries a ≥6-word passage that survives literal matching against `PRD.md` (initially 2 failures — an envelope citation with nested quotes and a `...`-abbreviated depreciation citation — both rewritten to full verbatim sentences and re-verified)
- **pytest collection**: 99/99 collect cleanly with `PYTHONPATH=.` and no server
- **pyflakes**: clean (no unused imports/bindings/undefined names)
- **No forbidden patterns**: no `pytest.mark.skip`/`skipif`/`xfail`, no "scaffold" mentions in generated code

## Key adjudication decisions

- All 22 difficulty and 55 corner instances passed the PRD-first two-condition filter — none were skipped. Notably, the waive→auto-close leg (`claim_waived_allows_autoclose_and_invoice_void_on_open`) was kept because PRD §3.5's gate ("closing additionally requires a POSTED or WAIVED claim") is only meaningful if claim transitions re-trigger close evaluation.
- The direct-GET-on-DEACCESSIONED leg (200) was kept, derivable from §2.9's `ERR_NOT_FOUND` condition ("resource id does not exist") plus §3.2's "soft-deleted but remains queryable."
- Priority-pair tests (state-vs-fiscal on dispatch, referential-vs-temporal on reserve, stale-vs-window) are legitimate because PRD §2.9 states the fixed numeric evaluation order verbatim.
- `hold_expires_at` assertions compare parsed datetimes (2026-08-04T00:00Z creation+72h; reset to 2026-08-05T00:00Z after amend at 08-02) rather than raw strings, since PRD §2.5 only pins timestamp formatting for `created_at`/`updated_at`.

## Step 6: Generate Implementation — 2026-08-14T05:20:00.000Z

Implementation complete for task_1627 (Costume & Prop Rental House). All files are in `/home/ubuntu/github/CodingPRD/tasks/task_1627_costume_prop_rental_house/workspace/implementation/`:

**Files**
- `start.sh` — executable launcher; guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, foreground, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — Flask entry, blueprint registration, envelope-wrapped error handlers (ApiError/404/405/500)
- `db.py` — in-memory `Store` (dicts keyed by id, boots empty, zero seeding), logical clock fixed at `2026-08-01T00:00:00Z`, 3-fractional-digit ISO timestamps, UUID ids, domain constants/enums
- `errors.py` — full 37-entry error catalog with per-error HTTP statuses from PRD §5
- `response.py` — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), list pagination meta (`limit`/`offset`/`total_count`/`has_more`, default 10, clamp 1..100)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role gating, RenterContact scope checks, and a lenient `BodyReader` that defers `ERR_VALIDATION` to priority 12 (after all business rules)
- `services.py` — all calculations (tiered rental quote with pinned rate card, per-line `round_half_up` division + condition multiplier, late fee, AGREED_VALUE/DEPRECIATED_REPLACEMENT valuation, inclusive-overlap availability, strict buffered unit selector, rush cleaning fee), renter-credit/serviceable-count recomputation with version bumps, suspension/cancel cascades, pull-list auto-close, production settle bubble-up, and the transitive daily sweep
- `routes_a.py` / `routes_b.py` / `routes_c.py` — all 44 endpoints

**Key fidelity decisions** (PRD over scaffold where they disagreed): per-error HTTP statuses (e.g., `ERR_QUANTITY_INVALID`→400, `ERR_INVOICE_EMPTY`→409); reservations fulfill only at dispatch (not submit); late fee uses the unit's post-update grade (`condition_grade_after`) per PRD §3.6 sentence order; validation order follows PRD §2.9 strictly (state → OCC → safety → referential → temporal → capacity → fiscal → shape); RenterContact lists are scope-filtered and cross-renter single-resource access returns 403; LOSS claims record `valuation_method=AGREED_VALUE` with full replacement value.

**Verification**: three smoke suites (~155 assertions) covering the full lifecycle — auth/scope/validation-order precedence, OCC 412s, DAILY/WEEKLY/LONG_RUN/deep-run pricing, per-line rounding, capacity vs. buffered unit-selector distinction, hold expiry boundary (`<=` confirm, sweep `>`), cert-expiry suspension cascade, manual suspend/reactivation gates, check-in severity branches, restoration gate, cleaning repair loop, rush-fee boundary at queue depth 10, damage valuation (both methods, grade D), SOD, dispute-after-billed, invoice sweep/void-unsweep, credit-hold gating (402), deaccession 3-step, transitive production advancement and settlement — all pass. Each suite ran against a freshly booted `start.sh` process, confirming clean per-test-server reboots with empty state. Note: port 10000 on this host is currently held by another task's server (task_1629), so final verification used a free port — the implementation reads `PORT` correctly.

## Step 7: Run Tests and Iterate — 2026-08-14T05:45:00.000Z

All sweep processes are finished; the two remaining PIDs belong to the long-running pipeline agent that owns this task, not my sweep. The exit criterion is met: all 8 rounds at 99/99.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each, 99 tests/round). Sweep 1: union of 3 failing tests. Sweep 2 (after fixes): all 8 rounds passed 99/99.

**Tests deleted:** None. (No test was fully deleted; one test was trimmed per the partial-coverage rule.)

**Tests modified (STEP 1b/1c — PRD does not uniquely determine the asserted outcome):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1627_costume_prop_rental_house/test_suite/test_01_catalog_envelope_pagination.py` — `test_list_pagination_defaults_and_limit_floor_rejected` renamed to `test_list_pagination_defaults` and the `limit=0 → ERR_VALIDATION 400` assertion removed (DEFAULT-VALUE/enforcement silence: PRD §2.3 states only "a minimum of 1 and a maximum of 100" without naming the out-of-range enforcement; rejecting with ERR_VALIDATION vs clamping are both PRD-faithful readings, and §2.9's ERR_VALIDATION list — "missing required field, wrong type, invalid enum member, or malformed date" — does not cover an in-range-typed but out-of-range query param). The PRD-covered default-pagination assertions (default limit 10/offset 0, `total_count`, `has_more`) were kept. Scaffold driver: corner instance `endpoints/list_pagination_defaults_and_limit_floor_rejected` over-reached the PRD prose.

**Tests fixed (STEP 2 — assertion mis-translated PRD):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1627_costume_prop_rental_house/test_suite/test_04_reservations.py` — `test_confirm_succeeds_once_production_confirmed`: the reservation is placed while the production is DRAFT, when no rate card is pinned (PRD §3.3 pins it at confirmation), so the 10-day window prices WEEKLY = 10000, and PRD §3.4 says confirmation "re-validates but does not recompute the quote" — the frozen value is 10000, not the LONG_RUN 8000 the test asserted (implementation was correct; 8/8 rounds showed `assert 10000 == 8000`). Assertion changed to 10000 with the freeze invariant documented.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1627_costume_prop_rental_house/test_helpers/api_client.py` — added `ApiClient.__init__` setting `self.session.headers["Connection"] = "close"`. Why: the runner SIGKILLs and re-spawns the server before every test while the session-scoped client lives on; a pooled keep-alive connection to the killed server could be reused by the next test's first request and fail with `ConnectionResetError(104)` (observed once in round 1 of sweep 1 on `test_derived_field_serviceable_count_reconciled`, 1.45 s in). Forcing connection-close eliminates the stale-socket flake class without touching any assertion.

**Fixes applied to `implementation/`:** None — the implementation was PRD-faithful on every disputed rule (WEEKLY 10000 freeze at confirm; inclusive-overlap capacity; clamping of out-of-range pagination params in a PRD-silent zone).

**Ops note:** the second sweep's wrapper shell was killed mid-run (exit 144) under heavy load from concurrent pipeline agents on this host; I relaunched it detached via `setsid nohup` and it ran to completion cleanly.

## Step 8: Finalize PRD — 2026-08-14T05:52:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1627_costume_prop_rental_house/workspace/PRD_FINALIZED.md` created with exactly one targeted edit.

**Line counts / delta:** PRD.md 361 lines → PRD_FINALIZED.md 361 lines; character delta +0.71% (single in-place paragraph extension, no new sections).

**Changes (one bullet per change):**
- §2.3 Pagination — revise — appended the previously unpinned enforcement rule: non-integer `limit`/`offset` is a wrong-type `ERR_VALIDATION`; out-of-range integers are clamped, not rejected (`limit`<1→1, `limit`>100→100, `offset`<0→0), and response `meta` echoes the clamped values — `implementation/response.py:32-56` (`_pagination_params`), `implementation/response.py:66-71` (`respond_list` meta).

**Step-7 items requiring no edit (with verification):**
- `test_04_reservations.py` quote-freeze fix — pure test mis-translation; PRD already uniquely determines the outcome: §3.4 quotes at creation ("its price quoted immediately"), §3.3 pins `long_run`/rate card only at production confirmation (so a DRAFT-production reservation prices WEEKLY for a ≥7-day window), and §3.4 states confirmation "re-validates but does not recompute the quote" and freezes `quoted_charge_cents`. Impl matches verbatim: `routes_b.py:244` (quote at creation via `compute_quote`), `services.py:68-96` (`bool(production.get("long_run"))` falsy for DRAFT → WEEKLY), `routes_b.py:293-320` (`confirm_reservation` never touches `quoted_charge_cents`). Prose kept verbatim.
- `test_helpers/api_client.py` `Connection: close` header — test-harness flake fix (stale keep-alive socket across per-test server restarts); no API behavior, no PRD edit.

**Per-edit pre-edit search log (NO-NEW-MISMATCH):**
- Edit 1 (§2.3 pagination):
  - (a) Subject: parsing and bounds enforcement of the `limit`/`offset` query parameters on list endpoints, and what values appear in response `meta`.
  - (b) Impl paths enumerated: `response.py:32-56` `_pagination_params` — the sole parser (defaults 10/0; `int()` failure or bool → `fail("ERR_VALIDATION")`; clamps `limit` to [1,100] and `offset` to ≥0); `response.py:59-77` `respond_list` — sole list responder, meta set from the clamped values; grep confirmed zero `paginate=False` call sites and no hand-rolled pagination; all 14 list-endpoint call sites route through `respond_list` with default pagination — `routes_a.py:83` (renters), `routes_a.py:193` (certificates), `routes_a.py:284` (rate cards), `routes_a.py:346` (items), `routes_a.py:483` (units), `routes_b.py:90` (productions), `routes_b.py:279` (reservations), `routes_b.py:445` (pull lists), `routes_c.py:50` (pull-list lines), `routes_c.py:195` (line assessment), `routes_c.py:258` (fitting authorizations), `routes_c.py:370` (damage claims), `routes_c.py:460` (cleaning tickets), `routes_c.py:589` (invoices). Also cross-checked §2.9 item 12 ("wrong type … `ERR_VALIDATION`") so the non-integer clause references rather than contradicts it.
  - (c) Wording adjustment: phrased as "clamped to the nearest bound rather than rejected" (mirrors impl exactly) and scoped the `ERR_VALIDATION` clause to non-integer values only, so the sentence does not reintroduce the removed test's claim that in-range-typed but out-of-range params are rejected; added "The clamped values are what the response `meta` reports" since `respond_list` echoes post-clamp values — consistent with all 14 enumerated call sites.

## Step 9: Complete PRD — 2026-08-14T06:05:00.000Z

All edits applied cleanly — every change is an in-paragraph insert/revision plus one new bullet line; no sections added. Final verification done via diff.

## Summary

**Source:** `PRD_FINALIZED.md` (361 lines, 61,499 chars) → `PRD_COMPLETED.md` (362 lines, 65,108 chars), char-delta **+3,609**.

**Counts:** 21 ambiguity-pins, 4 mismatch-revisions (25 change sites total; some bullets below bundle co-located pins made in one edit).

**Changes:**

- §2.1 — insert — ambiguity — `RenterContact` list endpoints over renter-owned resources silently filter to own resources; catalog/shared resources (items, units, rate cards, cleaning tickets) unfiltered — implementation/routes_a.py:77, routes_b.py:24-28,271-273,437-439, routes_c.py:42-44,250-252,361-363,582-583
- §2.2 — insert — ambiguity — all server-emitted timestamps (envelope `api_request_timestamp`, resource `created_at`/`updated_at`, workflow timestamps) read from the logical clock — implementation/response.py:16-20, db.py:123-134
- §2.2 — insert — ambiguity — unregistered path → `ERR_NOT_FOUND` 404; registered path with wrong method → `ERR_NOT_FOUND` body at HTTP 405 — implementation/app.py:28-35
- §2.3 — insert — ambiguity — `created_at` sort ties broken by creation sequence — implementation/db.py:201-202
- §2.4 — insert — ambiguity — clock set accepts any supplied instant, no monotonicity check — implementation/routes_a.py:27-35
- §2.4 — insert — ambiguity — sweep identifier arrays ordered by resource creation order — implementation/services.py:371-436
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — implementation/db.py:149-157
- §3.1 — insert — ambiguity — certificates listable by `status` filter — implementation/routes_a.py:189-191
- §3.1 — insert — ambiguity — renter PATCH rejects no-change status and any `PENDING_VERIFICATION` transition with `ERR_INVALID_STATE` — implementation/routes_a.py:109-114
- §3.1 — insert — ambiguity — `credit_limit_cents` patch immediately recomputes `credit_hold` (strictly-greater rule) — implementation/routes_a.py:132-135
- §3.1 — insert — ambiguity — sweep auto-suspension applies only to a currently `ACTIVE` renter — implementation/services.py:388-394, 269-274
- §3.1 — revise — mismatch — dropped the claim that reservation confirmation fails a suspended renter with `ERR_RENTER_SUSPENDED`; impl has no renter-ACTIVE check on confirm (cascade makes it unreachable → `ERR_INVALID_STATE`), so sentence now names reservation creation and dispatch — implementation/routes_b.py:293-320 vs 218-219, 540-542
- §3.2 — insert — ambiguity — `include_deaccessioned` true values: `true`/`1`/`yes`, case-insensitive — implementation/routes_a.py:337-338
- §3.2 — revise — mismatch — `DEACCESSION_PENDING` items remain visible in default list results; only `DEACCESSIONED` hidden (PRD said item "drops out" at request time) — implementation/routes_a.py:339-340
- §3.3 — insert — ambiguity — rate cards listable by `status` filter — implementation/routes_a.py:280-282
- §3.3 — insert — ambiguity — `DRAFT` production already carries computed `return_by_date`/`run_weeks`, `long_run` false, `rate_card_id`/`rate_card_version` null — implementation/routes_b.py:59-75
- §3.4 — revise — mismatch — reservation-confirm re-validation enumeration reordered to §2.9 evaluation order (state → hold-expiry → capacity → credit hold; original prose listed credit hold second) — implementation/routes_b.py:302-317
- §3.4 — insert — ambiguity — confirm capacity re-check excludes the reservation itself from the aggregate — implementation/routes_b.py:309-313
- §3.4 — insert — ambiguity — amend: omitted fields keep current values; capacity check excludes self — implementation/routes_b.py:359-371
- §3.5 — revise — mismatch — dispatch renter gates reordered to §2.9 order: `ERR_RENTER_SUSPENDED` → `ERR_INSURANCE_NOT_VERIFIED` → `ERR_CREDIT_LIMIT_EXCEEDED` (prose listed credit hold before insurance) — implementation/routes_b.py:540-548
- §3.6 — insert — ambiguity — check-in and report-lost responses return the updated pull-list line — implementation/routes_c.py:169, 182
- §3.6 — insert — ambiguity — check-in late-fee multiplier taken from post-update grade (`condition_grade_after`); grade `D` maps to 1.00; loss uses unit's unchanged current grade — implementation/routes_c.py:120-121, services.py:197-201, 447-448
- §3.7 — insert — ambiguity — "assessment date" = logical date the return assessment was created; DAMAGE valuation grade = unit's `condition_grade` at claim-creation time — implementation/routes_c.py:333-337, services.py:214
- §3.7 — insert — ambiguity — LOSS claims record `valuation_method` as `AGREED_VALUE` — implementation/services.py:210-212
- §3.7 — insert — ambiguity — posting or waiving a claim re-runs pull-list auto-close evaluation on the owning list — implementation/routes_c.py:399-403, 436-440

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1627_costume_prop_rental_house/workspace/PRD_COMPLETED.md`.
