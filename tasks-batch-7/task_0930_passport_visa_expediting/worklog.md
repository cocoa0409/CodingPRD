# Worklog — task_0930_passport_visa_expediting

Scenario (verbatim): `930. Passport & Visa Expediting Service: order & service level, document review & completeness, embassy/agency courier & appointment, status tracking & rush, government-fee vs service-fee, photo & form prep, rejection/RFE handling, delivery`

Difficulty: **beyond-Expert** (user request: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-08T12:27:04.000Z

Created `tasks/task_0930_passport_visa_expediting/workspace`. Index 0930 = highest existing (`task_0929_livescan_fingerprinting`) + 1.

## Step 3: Copy INSTRUCTION.md — 2026-08-08T12:27:04.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0930_passport_visa_expediting/workspace/INSTRUCTION.md` (1424 bytes). Performed in the same bash block as Step 1.

## Step 2: Generate scaffold — 2026-08-08T13:47:00.000Z

All three artifacts are generated and lint-clean.

### Files written
- `SCAFFOLD.yaml` (§1.0–§1.7 + `global_constants`)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

### Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    72
  §1.1 entities declared:     17
  §1.8 instances scanned:     18
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  789

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### G. Final counts
17 entities · 72 endpoints · **14 state-machine axes, 13 non-linear** (only `AgencyForm.status` is linear) across 95 transitions · **22 calculations, 7 dual-variant** · 38 error codes · **38-rung ladder** · 3 OCC rules on 3 distinct entities (`Applicant`, `AppointmentSlot`, `Order`) · 4 conservation invariants (money, custody cardinality, SLA partition, split partition) · **max cascade depth 5** · 48 declared constants · §1.8 = 9 rules / 18 instances · §1.9 = 9 sections / 58 instances (7 are `excluded_because` stubs).

Order carries four parallel axes (`workflow_status × payment_status × custody_holder × feasibility_status`).

### A. Incremental writes
Every file was emitted in 4–7 bounded appends; no single oversized Write.

### B. YAML lint
All three files `yaml.safe_load` clean. Three offender classes found and fixed: trailing `?` on flow-sequence input tokens (16 lines quoted), nested `[` inside `grounds: [errors[...]]` (7 lines quoted), and `$.data[2].id` inside a flow mapping (quoted).

### C. Undeclared-constant sweep
**0 undeclared.** Across all three files: 48 declared constants, 38 error ids, 141 enum members. Every `*_DAYS/_HOURS/_MONTHS/_CAP/_PCT/_CENTS/_MINUTES/_PX/_RATIO/_THRESHOLD/_UTC` token resolves to `global_constants`; the only two constant-shaped non-constants are the enum members `EXPIRES_AFTER_ISSUE_DAYS` / `VALID_BEYOND_RETURN_MONTHS`. Remaining ALL-CAPS tokens are prose emphasis (`NON-FUNGIBLE`, `ROUND PER LINE THEN SUM`) or envelope placeholders.

### D. Reachability audit — defects found and repaired
1. **`ERR_REQUIRED_DOCUMENTS_INCOMPLETE` was graph-unreachable** — rung 10 (`ERR_INVALID_STATE`) always pre-empted it since `READY_FOR_SUBMISSION` implies all docs accepted. Fixed by *scoping the higher rung*: submit accepts `INTAKE` **and** `READY_FOR_SUBMISSION` as from-states, and rung 34 owns the INTAKE case (four such exclusions are enumerated explicitly in rung 10's text).
2. **`REFUND_PCT_AT_AGENCY: 0.00` made `payment_status = REFUND_PENDING` arithmetically unreachable** (post-tender refund was always 0, and the transition requires refund > 0). Changed the constant to `0.15`.
3. **`REFUND_PENDING → REFUNDED` was arithmetically infeasible** (a post-tender refund can never equal `collected_cents`). Deleted the edge; `REFUNDED` remains reachable via the pre-tender path.
4. **`Applicant.readiness_status = SPLIT_OUT` had no producer** (a split moves the applicant but keeps it COMPLETE). Removed from the enum.
5. **`ServiceCatalogItem.status = RETIRED` had no producer** (no retire endpoint). Removed the field.
6. **`Shipment.delivery_status = RETURNED` had no producer.** Removed from the enum.
7. **Money conservation was true by construction** (`outstanding` was a residual). Fixed per the "introduce the one optional field" rule: `outstanding_cents` is now maintained incrementally and `POST /payments` gained the optional `stream_override`, the only way to break the per-stream ceiling → rung 31 `ERR_STREAM_ALLOCATION_INVALID`.
8. **The delivery escalation surcharge broke conservation** (an `EARN` with no funding, driving `outstanding` negative). Re-modelled as a *new charge* raising `service_fee_quoted_cents`/`total_quoted_cents` with no LedgerEntry.
9. **Refunds after revenue recognition drove `outstanding` negative.** Added a pinned `refund_draw` waterfall (outstanding first, then de-recognise `service_earned_cents`).
10. **Under-determined values pinned** rather than left to the implementer: the auto-created return leg's `leg_index`/`scheduled_date`, the split admin fee as `min(SPLIT_ADMIN_FEE_CENTS, outstanding)`, the child order's initial custody, the post-split re-quote rule (`promo_discount_pct = 0.00`), the custody reason for AGENCY-origin dispatch, and defaults for `validity_param` / `applies_max_age_years`.
11. **`MINOR_AGE_THRESHOLD_YEARS` was declared but unused** — made load-bearing as the `applies_max_age_years` default for `PARENTAL_CONSENT`.

Arithmetic feasibility was computed for every cap: `PHOTO_RETAKE_CAP 3`, `DOCUMENT_RESUBMISSION_CAP 2`, `COURIER_REDISPATCH_CAP 2` (3 attempts), `DELIVERY_ATTEMPT_CAP 3`, `APPOINTMENT_RESCHEDULE_CAP 2`, `NO_SHOW_REBOOK_CAP 2`, `RFE_ROUND_CAP 2` (both order-level and per-RFE), `MAX_DISCOUNT_PCT 0.25` (auto 0.10 + promo 0.20 clips), and the `MULTI_APPLICANT_WAIVER_FLOOR_CENTS 20000` floor — all hittable from both sides. Automated checks confirm: 0 unbound `${var}` across 789 calls, 0 unresolved `grounds`, 0 duplicate instance names, every one of the 38 error codes referenced by a design instance, and every `excluded_because` target resolving to a real §1.8 instance name.

### E. Verb-scoping check
All **18** §1.8 instances audited; **0 widenings**. The highest-risk pair was rung 24 (`ERR_FORM_REVISION_STALE`, `applies_to: POST .../prepared-forms`) — its instance triggers `prepare`, not the sibling `sign`. Similarly rung 19 (`book`/`reschedule`) is exercised with `book`, and rung 23 with `retake`, not `compliance-check`.

### F. Instance grounds check
Every asserted literal was computed in Python against the declared formulas and constants — e.g. `27339` vs the sum-then-round `27338`; the discount trap (`68250` no-promo → `70125` with a 5% promo, because the post-discount subtotal `19125 < 20000` forfeits the `3000` waiver); refunds `15188 / 10125 / 5063 / 1575`; the split partition `16000 + 6750 = 22750` with `68250 == 45500 + 22750`; SLA `480 running / 360 paused / 840 gross`; and business-date arithmetic (`projected 2026-06-26` vs `deadline 2026-06-26` → FEASIBLE at the boundary).

### Seams exploited
All 12 domain seams are used and interlocked. The depth-5 cascade is the form-revision chain `AgencyForm → PreparedForm → Applicant → Order → CourierLeg`; a second depth-4 cascade from a different trigger runs `Order → Applicant → Appointment → AppointmentSlot`. The agency-custody write gate sits at rung 8 with an exhaustive 11-item exclusion list and pre-empts 30 lower rungs.

### Orchestrator independent verification
- All three files `yaml.safe_load` clean; top-level keys correct (SCAFFOLD.yaml has no `scaffold_difficulty_design`/`scaffold_corner_design` key).
- Section counts re-derived from parsed YAML: entities 17, endpoints 72, state_machines 14, calculations 22, validations 38, errors 38, global_constants 48 — matches the subagent's report.
- Independent constant-shaped-token sweep (`*_DAYS|_HOURS|_MONTHS|_MINUTES|_YEARS|_CAP|_LIMIT|_BUFFER|_WINDOW|_THRESHOLD|_MAX|_MIN|_CENTS|_RATE|_PCT|_RATIO|_PX|_FLOOR|_CEILING|_COUNT|_UTC`): 43 tokens, 41 resolve to `global_constants`, 2 residuals (`EXPIRES_AFTER_ISSUE_DAYS`, `VALID_BEYOND_RETURN_MONTHS`) confirmed by grep to be `validity_rule` enum members, not constants. **0 undeclared.**

## Step 4: Generate PRD — 2026-08-08T14:08:00.000Z

PRD complete and verified.

### Output
`workspace/PRD.md` — **749 lines, 19,502 words**. Ends cleanly at §5's last error row (`ERR_GOVERNMENT_FEE_FORFEIT_UNACKNOWLEDGED | 422`); no audit footer. The withheld design YAMLs were never opened.

### Section map
§1 Introduction · §2 Global Specs: 2.1 Operators/Roles/Identity, 2.2 Response Structure (verbatim), 2.3 Pagination/Ordering/Filtering, 2.4 Identity/Timestamps/Version, 2.5 Logical Clock & Business Calendar, 2.6 Two Money Streams & Rounding, 2.7 Custody & Agency Write Gate, 2.8 OCC, **2.9 The 38-Rung Ladder** (2.9.1 closed enum routing, 2.9.2 admitted from-states, 2.9.3 verb-scoped rungs, 2.9.4 custody scopes, 2.9.5 closure scopes), **2.10 Version-Bump Ledger**, **2.11 The Four Conservation Invariants**, 2.12 Response Projections & Formula Intermediates · §3 Workflows (3.1 catalogue/paperwork, 3.2 form publish + 5-hop cascade, 3.3 missions/closures/slots, 3.4 order + travellers, 3.5 pricing/tier change, 3.6 collection/accept, 3.7 readiness, 3.8 courier/custody, 3.9 projection/feasibility/submission, 3.10 agency/RFE/SLA, 3.11 decision/refund/delivery, 3.12 split/cancel/abandon) · §4 72 endpoints (4 cols) · §5 38 errors (2 cols).

### Verification
- **Constants: 48/48 present with literal values** (machine-swept against `global_constants`).
- **Contract 1 — Field coverage:** entities 124/124, request-body+computed-output 86/86, query params 22/22, 0 missing. **PASS**
- **Contract 2 — Rule coverage:** 38/38 ladder rungs with priority order; 3/3 OCC rules (endpoint + `expected_*_version` + `ERR_STALE_VERSION` + 412); all 14 state-machine axes and every transition; 22/22 calculations incl. all 7 dual-variant selectors; 38/38 error ids reachable in §2/§3; all endpoint side-effects. **PASS**
- **Contract 3 — §3 path purity:** 1,223 backtick tokens, 0 leading-slash, 0 bare-method, 0 method+path. **PASS**
- §2.2 byte-identical to `section-2.2-response-structure.md`; no fuzzy/approximating words.

Required items all landed: version-bump ledger (§2.10, 42 operations with non-bumping branches), 38-rung ladder with the exhaustive rung-8 exclusion list (§2.7/§2.9), one uniform timestamp rule — 3 fractional digits + `Z` for every server instant and every echoed caller instant (§2.4), closed enum-routing list of 17 fields plus the two deliberate exclusions (§2.9.1), 4 invariants incl. pinned refund-draw waterfall and per-stream ceiling (§2.11), per-entity projections + never-serialised intermediates (§2.12), list sort keys with tie-breaks and off-enum filter behaviour (§2.3), dual-variant rounding order pinned round-per-line-then-sum (§3.5).

### Friction points carried forward un-prejudged (16 — a new max; prior max was 12 on task_0925)
1. **§3.8 / rung 9 — terminal orders vs. the return dispatch.** Custody axis declares the `AGENCY → COURIER` return hop from `workflow_status` `APPROVED`, `REJECTED`, `CANCELLED`, `ABANDONED`; rung 9 refuses every mutating endpoint on a terminal order and dispatch/complete carry no rung-9 exemption. Readings: (a) rung 9 wins and post-tender refunds on abandoned/agency-cancelled orders can never be disbursed; (b) the custody transition wins and dispatch/complete are implicitly rung-9-exempt. Both statements rendered.
2. **§3.8 — which legs a cancellation cancels.** Leg axis declares `CREATED → CANCELLED` and `FAILED → CANCELLED`; the cancel operation says "`CREATED` or `FAILED`"; two workflow cancel transitions say "`CREATED` or `DISPATCHED`". Both rendered.
3. **§3.11 — `SERVICE → APPLICANT` custody.** First-attempt `DELIVERED` moves the book `SERVICE` → `APPLICANT` in one request, but the custody axis declares only `COURIER → APPLICANT` (requiring `custody_holder == COURIER`, open event `leg_index` null) and no `SERVICE → APPLICANT` edge. Both rendered.
4. **§3.12 — the split admin fee.** Calculation: `min(1500, parent.outstanding_cents after the transfer)`. Operation description: flat 1500. Both rendered.
5. **§3.12 — traveller withdrawal on an at-agency cancellation.** The operation says every cancellation withdraws travellers and cancels their `BOOKED` appointments; the `AT_AGENCY → CANCELLED` transition lists only money/SLA/leg effects. Both rendered.
6. **§3.11 — `signature_captured` present-but-false.** Transition requires "carries `signature_captured == true`"; `ERR_VALIDATION`'s condition says "absent". A present-and-false value is covered by one reading and not the other.
7. **§2.11 / §3.11 — `outstanding_cents` under a refund.** Field description: every `REFUND` subtracts from `outstanding_cents`. `refund_draw`: draw from outstanding first, remainder from `service_earned_cents`. Rendered with the waterfall governing and the tension named in prose.
8. **§3.9 — the feasibility read.** Listed as a trigger of `projected_completion_date`/`feasibility_evaluation`, yet declared with empty side effects. Rendered as a pure read that persists nothing; readings: (a) recompute-and-report only, (b) recompute-and-write (which would also revoke acknowledgments on a GET).
9. **§3.9 — submission's `custody_holder == SERVICE` precondition** has no nominated ladder rung (rung 14's four scopes exclude submission). Rendered as a requirement, with the note that the reachable configuration is stopped at rung 36 via `feasibility_status` `UNKNOWN`.
10. **§3.5 — pre-intake tier re-quote and the promo.** "Discount and waiver are re-evaluated", but the service-level payload carries no `promo_discount_pct`. Readings: promo treated as 0.00 (rendered) vs. reuse of the order's recorded `discount_pct_applied`.
11. **§3.7 — `filled_field_count`.** Declared bound `>= 0`; field definition says it must be at least the revision's `required_field_count`. Both rendered.
12. **§3.12 — cancellation actor.** Endpoint role list is `CaseManager` + `Traveler` at every stage; the `SUBMITTED → CANCELLED` and `AT_AGENCY → CANCELLED` transitions name `CaseManager` only. Both rendered (rung 2 reads the endpoint list).
13. **§2.9.2 / §3.5 — unnominated transition preconditions.** Quoting with no `PENDING`/`COMPLETE` traveller, accept-quote while not `COLLECTED`, appointment outcome before `starts_at`, and the `SERVICE`-origin dispatch requiring `workflow_status` `SUBMITTED` all have no dedicated error code; each routed to `ERR_INVALID_STATE` at rung 10 as the nearest owning rung.
14. **§2.3 — off-enum filter values.** Rung 7's list is closed and rung 6 does not cover query strings. Rendered as an empty page; alternative reading is `ERR_VALIDATION`.
15. **§3.12 — the split response body.** Scaffold declares `output: Order` with 201 without naming which order. Rendered as the child, on the 201-Created + envelope rule.
16. **§3.11 — refund reason on post-tender disbursement.** The payment axis pins `REJECTION_REFUND` for all post-tender disbursements, including those originating from an at-agency cancellation or an RFE abandonment. Rendered as declared.

### Orchestrator independent verification
749 lines / 19,502 words confirmed; document ends mid-table at the final error row, not mid-sentence; 37 headers, 5 top-level sections; grep for `difficulty_design|corner_design|test_recipe|§1.8|§1.9` → **0 hits** (no design-index leakage).

## Steps 5 + 6: Unit tests and implementation (launched concurrently in one message) — 2026-08-08T14:53:00.000Z

### Step 5 summary (verbatim)

**Total: 87 tests** across 12 files, all compiling, all collected by pytest (`87 tests collected`), `test_helpers` imports cleanly.

**Queue-A coverage: 18/18 instances, exactly 2 tests each (36 tests).**
**Queue-B coverage: 51/51 non-stub instances, exactly 1 test each (51 tests).** The 7 `excluded_because` stubs were not translated; their `difficulty_instance` cross-references were verified to resolve (0 broken pointers).

**Instances SKIPPED: none.** Every instance survived the PRD-first two-condition filter. No verb-scoping failures were found — for every instance the asserted operation matched the verb in its cited grounds (rung 21↔resubmit, 22↔accept, 23↔retake, 15/25↔dispatch, 20↔reschedule, 24↔prepare, 12/34–37↔submit, 26↔delivery attempt, 38↔cancel).

**Deviations made (3 input deviations + 1 assertion re-target):**

1. **`Difficulty/resource_temporal_overlap/custody_interval_single_occupancy_rejects_out_of_position_dispatch`** — leg 2's `from_holder` changed **`AGENCY` → `APPLICANT`**. On a `DRAFT` order an `AGENCY`-out hop also violates §3.8's "declared while `workflow_status` is `APPROVED`, `REJECTED`, `CANCELLED` or `ABANDONED`", a precondition §2.9.2 gives no rung — one of the un-adjudicated frictions, so one reader lands on `ERR_INVALID_STATE` (rung 10) and another on `ERR_CUSTODY_MISMATCH` (rung 14). With `APPLICANT` there is no workflow precondition and rung 14 is the only rung that can fire under both readings. The instance's claim and all its assertions are asserted unchanged.

2. **`Corner/entities/corner_custody_event_is_immutable_and_carries_no_version`** — the clock is advanced to `10:00Z` before the dispatch and `11:00Z` before the completion. The recipe left all three handovers on one instant, but the instance asserts a *positional* row order and §2.3 tie-breaks equal `acquired_at` by `id` (a random server-minted UUID), so the ordering was not derivable. `scheduled_date` stays `2026-06-01`, so rung 16 is unaffected; no assertion changed.

3. **`Corner/cross_cutting_complexity_layers/corner_prepared_form_create_supersedes_prior_to_void`** — a compliant photo upload + compliance check added to the setup. The recipe supplies no photo yet asserts `readiness_status == COMPLETE`; §3.7 requires exactly one `PASSED` photo, so the assertion could not hold as written. Adding the photo makes every one of the instance's assertions true and derivable rather than dropping one.

4. **`Difficulty/boundary_precision_check/feasibility_projection_equal_to_deadline_is_feasible`** (assertion re-target, not an input change) — the instance's final assertion `Order.effective_submission_date == 2026-06-01` contradicts §3.9 verbatim ("the stored `effective_submission_date` on the order itself is written only at submission and stays null until then, while the read reports the value its own projection used"); the order is unsubmitted. The same value is asserted on the field the PRD does pin: `effective_submission_date` as returned by `GET /expediting/orders/{id}/feasibility`. All other assertions translated unchanged.

**Verified mechanically** (script in scratchpad, run against every test): every test carries **exactly one** `Design:` tag, every tag resolves to a real non-stub instance, every PRD citation is **verbatim** (whitespace-normalised substring of `PRD.md`, ≥8 words), and there are **0** occurrences of `pytest.mark.skip` / `skipif` / `xfail` / `pytest.skip` anywhere. No timestamp is compared as a raw string — the two instant assertions go through `assert_same_instant`, and `assert_sla_partition` uses it internally. No reference to `implementation/`, and no scaffold vocabulary in generated comments or docstrings.

**Frictions respected:** the split admin fee is asserted only where min-of and flat-1500 agree (parent outstanding 45500 ≫ 1500); `outstanding_cents`-under-refund is asserted only where the waterfall and the running-balance reading agree; terminal-order return dispatch, cancellation leg scope, at-agency traveller withdrawal, `signature_captured` present-but-false, and the post-tender disbursement reason are never asserted.

**File layout:**
```
test_helpers/  __init__.py  types.py  api_client.py (72 endpoint methods)  api_errors.py
               assertions.py (incl. parse_instant / assert_same_instant / conservation +
               custody-cardinality + SLA-partition checkers)  factories.py  constants.py
               test_users.py  fixtures.py (primitives + build_scenario walking
               draft→quoted→intake→ready→submitted→at_agency)

test_suite/    conftest.py
               test_01_catalogue_and_form_revisions.py      (8)
               test_02_orders_and_travellers.py            (11)
               test_03_pricing_and_quoting.py              (10)
               test_04_payments_and_money_streams.py        (4)
               test_05_documents_and_photos.py              (8)
               test_06_appointments_and_slots.py            (7)
               test_07_custody_and_courier_legs.py         (10)
               test_08_feasibility_and_submission.py       (11)
               test_09_agency_rfe_and_sla_clock.py          (7)
               test_10_decision_refunds_and_delivery.py     (4)
               test_11_split_and_conservation.py            (5)
               test_12_access_control.py                    (2)
```

### Step 6 summary (verbatim)

Implementation complete at `workspace/implementation/`.

**Module layout — 4,265 lines, 31 files.** Foundation: `app.py` (114), `constants.py` (149), `clock.py` (106), `store.py` (100), `errors.py` (96), `envelope.py` (49), `calendar_util.py` (114), `serializers.py` (285), `validation.py` (364). Services: `money.py` (216), `lookup.py` (143), `readiness.py` (109), `pricing.py` (96), `cascade.py` (89), `projection.py` (82), `sla.py` (81), `custody.py` (49), `slots.py` (42), `legs.py` (26). Routes: `order_routes.py` (415), `document_routes.py` (342), `config_routes.py` (290), `order_ops_routes.py` (226), `rfe_routes.py` (178), `shipment_routes.py` (175), `appointment_routes.py` (159), `courier_routes.py` (127), `common.py` (42).

**Route completeness gate — 72/72, MISSING 0, EXTRA 0.** Scaffold `endpoints[]` parsed programmatically (72 unique method+path), app booted in-process, `app.url_map` dumped, paths normalized (`<x>`/`{x}` → `{}`), sets diffed. `GATE: PASS`.

**Bug 1 — timestamp rendering drift (adjudicated).** One rule, one helper. `clock.render_instant()` is the **sole** producer of every instant in every response — `created_at`, `updated_at`, `api_request_timestamp`, `published_at`, `quoted_at`, `submitted_at`, `tendered_at`, `decided_at`, `signed_at`, `booked_at`, `acquired_at`, `released_at`, `recorded_at`, `issued_at`, `deadline_at`, `responded_at`, `started_at`, `ended_at`, `current_utc`, and pass-through caller instants (`starts_at`, `to_iso8601`). It truncates microseconds to exactly 3 digits + `Z`. Dates go through `render_date()` as bare `YYYY-MM-DD`. HTTP-verified: caller sent `to_iso8601: "2026-05-04T08:00:00.123456Z"` → echoed `current_utc` = `2026-05-04T08:00:00.123Z`, and the server-written `quoted_at` on the same clock = `2026-05-04T08:00:00.123Z` (identical style). Also `"2026-05-04T11:30:00.987654+02:00"` → `"2026-05-04T09:30:00.987Z"` (offset normalized, 6→3 digits), and a caller `starts_at: "…T10:00:00.000000Z"` → `"…T10:00:00.000Z"`.

**Bug 2 — enum-membership routing (adjudicated).** Exactly 17 fields route to `ERR_INVALID_ENUM` (422) via `Body.enum`; grep confirms 18 call sites (`service_level` appears twice, on order creation and on the tier change, which the PRD lists as one entry) and no others: `service_level` (order create + service-level), `visa_type`, `government_fee_basis`, `doc_type` (requirement create), `validity_rule`, `doc_type` (document submission), `background_code` (upload + retake), `from_holder`, `to_holder`, `method`, `requested_doc_type`, `decision` (document review), `outcome` (courier-leg completion), `outcome` (appointment outcome), `outcome` (RFE adjudication), `decision` (agency decision), `stream_override`. **Both exclusions honored:** (1) `outcome` on a **shipment delivery attempt** uses the separate `Body.non_enum_choice` helper (the only call site) → `ERR_VALIDATION` 400, HTTP-verified with `{"outcome":"BOGUS"}` → 400 `ERR_VALIDATION`; (2) enum-valued **query filters** never error — `apply_filter` does exact string equality, so `?workflow_status=NOT_A_STATUS` returns 200 with an empty array, `total_count` 0, `has_more` false.

**The 16 friction points — reading chosen + reachability argument:**
1. **Terminal-order return dispatch vs rung 9** → dispatch/complete are **exempt from rung 9**. Otherwise the AGENCY→COURIER hop declared from `CANCELLED`/`ABANDONED`, and with it the post-tender refund disbursement, would be unreachable on both terminal paths. (Verified: an ABANDONED order's return leg dispatches, completes, and disburses.)
2. **Which legs a cancellation cancels** → **CREATED or FAILED**, and only from `INTAKE`/`READY_FOR_SUBMISSION` (§3.12's stage-scoped prose + the scaffold state machine agree). The `DISPATCHED` reading would leave `FAILED → CANCELLED` unreachable and invent an undeclared transition; the stage scoping also keeps the AT_AGENCY return leg alive.
3. **`SERVICE → APPLICANT` on first-attempt delivery** → **direct handover** implemented. Requiring a COURIER intermediary would make the declared shipment `CREATED → DELIVERED` transition (whose own precondition is `custody_holder == SERVICE`) unreachable.
4. **Split admin fee** → **min(1500, outstanding after transfer)**. Flat 1500 can drive `outstanding_cents` negative, breaking Invariant 1 and making `conservation_ok: true` unreachable; min-of agrees with flat whenever outstanding ≥ 1500.
5. **Traveller withdrawal on an AT_AGENCY cancel** → **withdraw on every cancellation**. Keeps the Appointment `BOOKED→CANCELLED` → slot-release cascade reachable from an at-agency cancel; the Applicant axis states the trigger with no stage qualifier.
6. **`signature_captured` present-but-false** → **must be literally `true`**; absent, `false` or non-boolean all fail rung 6. "Carries `signature_captured` set to true" is not satisfied by `false`, and this keeps the catalogued `ERR_VALIDATION` condition reachable in both shapes.
7. **`outstanding_cents` vs the refund waterfall** → **the pinned draw governs** (PRD says so outright). `outstanding -= min(refund, outstanding)`, remainder off `service_earned_cents`, `refunded += refund`. Keeps Invariant 1 exact and `conservation_ok: true` reachable on every path.
8. **Does the feasibility read persist?** → **pure read**. It returns the *stored* `feasibility_status` and a freshly computed projection; persisting would let a GET revoke acknowledgments and would make "stored value survives" unreachable. Verified byte-identical order row before/after.
9. **Submission's `custody_holder == SERVICE` with no rung** → **not enforced as its own check**. §2.9.4 closes `ERR_CUSTODY_MISMATCH` to four operations that exclude submission; the PRD's own reasoning routes the outcome to rung 36 via `feasibility_status = UNKNOWN`. Inventing a rung would emit an uncatalogued precedence.
10. **Pre-intake re-quote and the promo** → **promo treated as 0.00** on a tier-change re-quote (matching the split's identical rule). Keeps the "discarded, not adjusted" re-quote variant behaviourally distinct from the in-flight delta. Verified: 0.15 → 0.10 after upgrade.
11. **`filled_field_count`'s lower bound** → **both bounds carried** at rung 6 (`>= 0` **and** `>= required_field_count`), both `ERR_VALIDATION`. Enforcing only `>= 0` makes the second stated requirement dead text.
12. **Cancellation actor role list** → **CaseManager and Traveler at every stage**. Rung 2 reads the endpoint's authorized-role list, and no error is nominated for a stage-restricted actor.
13. **Four preconditions with no error code** → routed to **rung 10 `ERR_INVALID_STATE`** where they are genuinely state conditions on the target (adjudicate-`EXPIRED` before the deadline; agency decision with an outstanding RFE; signing against a non-ACTIVE revision), and **not enforced** where §2.9.2 declares its admitted set "exact" (the per-hop workflow conditions on dispatch — leg_status alone gates it) or where the PRD explicitly resolves it elsewhere (submission custody, #9). Tender's `tendered_at is null` is unreachable-as-a-failure given rung 10 admits only `SUBMITTED`.
14. **Off-enum filter values** → **empty page**, `total_count` 0, `has_more` false — never 404 and never a validation error.
15. **Which order the split returns** → **the newly created child** (201), per §3.12's explicit sentence; the child is pinned at `version` 1 even when its readiness gate advances in the same request.
16. **Refund reason on post-tender disbursement** → **`REJECTION_REFUND`** for every post-tender disbursement (rejection, at-agency cancel, RFE abandonment); `CANCELLATION_REFUND` for the immediate pre-tender rows. Both reason values stay reachable.

Bonus sub-adjudication (same family): rung 4's "no slot for this `doc_type`" check runs **only for declared enum members** — otherwise every off-enum `doc_type` would be swallowed as 404 and `ERR_INVALID_ENUM` on that field would be unreachable. Both are HTTP-verified (`EMPLOYMENT_LETTER` → 404, `GIBBERISH` → 422).

**Storage prohibitions — confirmed.** No seeding, preloading or hardcoded entities anywhere (`store.Store.reset()` creates 17 empty dicts; a fresh boot returns `total_count: 0` for every collection). In-memory dicts only: no SQLite, no disk, no `/tmp`, no external persistence. Domain logic reads **only** the logical clock (default `2026-05-01T00:00:00Z`); grep confirms zero `datetime.now`/`utcnow`/`time.time()` uses — even `api_request_timestamp` comes from the logical clock.

One deliberate design choice worth flagging: ids are **monotonic UUID-v4-shaped strings** (48-bit counter in the high bits). PRD §2.3 makes the `id` tie-break load-bearing *because* the coarse logical clock puts many rows at one `created_at` — with random UUIDs that tie-break is arbitrary and same-instant list ordering is nondeterministic (a genuinely flaky SLA-segment ordering was caught this way). Monotonic ids keep them valid server-minted UUID strings while making ascending-`id` mean creation order.

**start.sh contract.** `set -euo pipefail`, `cd "$(dirname "$0")"`, **guarded** dependency install (`if ! python3 -c "import flask"`), `PORT` read with default 10000, `exec python3 app.py` in the foreground. `app.py` creates the listening socket itself with `SO_REUSEADDR` (+`SO_REUSEPORT` where available), binds `0.0.0.0:$PORT` in a **retry loop tolerating EADDRINUSE** (40 attempts × 0.25 s), then serves via `werkzeug.serving.make_server(..., threaded=True, fd=sock.fileno())` on the already-bound socket — so Werkzeug's `sys.exit(1)` bind path is never reached. A 12-round tight kill/relaunch simulation of `--isolation per-test-server` produced **0 start failures**.

**Verification performed.** Four HTTP smoke suites (~230 assertions) covering the full lifecycle, the depth-5 publish cascade, the depth-4 rejection cascade, both refund variants and the disbursement, the split partition, the RFE loop with re-open and abandonment, hold-for-pickup, delivery escalation, all four conservation invariants, per-line rounding, the discount trap, OCC, ladder precedence (rung 3>6, 6>7, 8>10, 14>15, 36 before submit) and RBAC — run **3× each on fresh boots: 12/12 PASS**, plus the route gate re-verified after every change.

### Orchestrator independent verification (Steps 5+6)
- **Isolation overlap:** Step 5 finished ~3 min BEFORE Step 6, so `test_suite/`+`test_helpers/` were on disk during impl-gen's final stretch. **Containment held both directions:** grep of `implementation/` for `test_suite|test_helpers|conftest|def test_` → 0 hits; grep of `test_suite/`+`test_helpers/` for `implementation/|from app|import app|from store|from errors|from serializers` → 0 hits.
- `def test_` count = **87**; `Design:` tags = 87 (36 Difficulty + 51 Corner), matching 18×2 + 51×1 exactly.
- skip/xfail/skipif/pytest.skip across both test dirs = **0**.
- Impl: 30 `.py` files, 4,268 lines, all compile; grep for `sqlite|json.dump|pickle|/tmp|datetime.now|utcnow|time.time()` → **0 hits**; `start.sh` + `requirements.txt` present.
- **Independent route diff** (scaffold `endpoints[]` vs in-process `app.url_map`, path params normalized): scaffold 72, impl 72, **MISSING 0, EXTRA 0**.
- Pre-staged `workspace/sweep.sh` for Step 7 as **2 waves of 4** (8-core host, load 0.48, no co-tenant pipelines), with a `SWEEP_DONE` marker and no inline `pkill`.

## Step 7: Run tests and iterate — 2026-08-08T15:05:00.000Z

The sweep passed clean on the first iteration, so no fixes were required. Verified independently rather than trusting the sweep's own summary.

**Iterations run:** 1 (8/8 rounds green on the first sweep — no fix/rerun cycles needed).

**First-iteration isolation-overlap audit — verdict: PASS, no contamination found.**

Steps 5 and 6 overlapped on disk, so the four mandated checks plus a containment re-grep were run:

- *Cross-reference containment* — 0 hits in both directions. No test imports or references `implementation/`, `app`, `store`, `serializers`, or manipulates `sys.path`; no implementation file mentions `test_suite`, `test_helpers`, `conftest`, or `pytest`.
- *Values traceable to PRD, not to code* — 142 distinct subscript/`.get` field names referenced across the suite; 13 are fixture-internal dict keys (`traveler_headers`, `leg1`, `prepared_forms`, …), and **all 129 real response/payload field names appear verbatim in PRD.md**. Of 28 numeric literals ≥3 digits in assertions that are not verbatim PRD tokens, all are *derived arithmetic*, not module-internal constants. The pricing chain was hand-derived end-to-end from PRD §3.5 prose to confirm: 3 travellers × 7500 base × (1+0.00 STANDARD) × (1−0.10 auto discount) = 6750/line → 20250 subtotal → waiver granted (count ≥3 **and** subtotal ≥20000) → handling 0 → `service_fee_quoted_cents` 20250; `PER_APPLICANT` gov 16000×3 = 48000 → total 68250, `PER_ORDER` 16000 → total 36250. Both match the test's asserted 68250/36250. The eight PRD threshold constants (20000, 3000, 2500, 0.25, 0.10, 0.35, 0.80, 1500) are all verbatim in PRD.
- *Timestamps are semantic* — `test_helpers/assertions.py` defines `parse_instant`/`assert_same_instant` (parse → normalize to UTC → compare instants); 22 instant-assertion call sites use them. **Zero raw-string timestamp equality assertions** anywhere in the suite.
- *List positions are PRD-guarded* — every server-returned list index traces to a stated ordering rule: PRD line 80 (default `created_at` asc, `id` asc tie-break), line 84 (legs by `leg_index` asc), line 85 (custody events by `acquired_at` asc), line 86 (SLA segments by `started_at` asc). The one apparent exception, `lineage[-1]` in `test_05`, indexes a list the test builds itself from its own sequential calls — not a server ordering dependency.
- *Id-format detail not leaked* — tests assert only `is_valid_uuid` (from the runner's own `prd_bench_local_runner.testing`). Nothing asserts the monotonic-counter-in-high-bits design, so that determinism measure stays invisible to the suite as intended.

**Tests deleted:** none. No test failed in any round, so no test reached STEP 1.

**Fixes applied to `test_suite/`:** none.
**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `implementation/`:** none. The tree is byte-identical to what Step 6 produced.

**Cardinal-rule sanity pass** (verified before sign-off, since a clean first sweep gets no other scrutiny): route set is exactly **72 rules / 72 method-endpoints**, unchanged; **no** persistence or seeding smells (`sqlite`, `open(`, `json.dump`, `pickle`, `/tmp`, `shelve`, `redis` all zero hits); **no** wall-clock use in domain code (`datetime.now`, `datetime.utcnow`, `time.time()` all zero hits — the logical clock is the only time source).

**Final per-round results** (read directly from each `results.${i}.json`, not from the sweep's summary line): all 8 rounds 87/87, 87 rows, 87 unique test names, all `passed`.

**Union of non-passing tests across all 8 rounds: empty** — no flakiness signal either (no test passed in one round and failed in another). Each `round.N.log` contains exactly one `Killed` (the expected per-test-isolation server swap ahead of test #1) and zero tracebacks or "could not be restarted" errors — notably, **none of the EADDRINUSE respawn flake** that has bitten earlier tasks (the pre-bound-socket + `make_server(fd=)` measure in Step 6 held).

**Caveat raised by the subagent and carried forward:** a clean first sweep means the test generator's avoidance of the 16 un-adjudicated friction points was never stress-tested by a failure. The audit confirms the suite doesn't *read* the implementation, but "no test asserts on a friction point" is evidenced only by the absence of failures, not by a positive check of each of the 16 against the 87 tests. → **Closed by a dedicated friction cross-check pass run alongside Step 9 (recorded below).**

### Orchestrator independent verification (Step 7)
- All 8 `results.N.json` re-parsed directly: each has **87 individual rows** (not just an aggregate counter), `passed=87 failed=0 total=87`, 87 unique test names, status set exactly `{'passed'}`.
- Sorted test-name lists **byte-identical to round 1 in all 8 rounds** (catches a round that silently collected a smaller suite).
- `find implementation test_suite test_helpers -newer results.1.json` → **empty**, proving the green result describes the shipped tree.
- Per-round logs: `Killed` exactly 1 each (expected pre-boot server swap), `traceback` 0, `could not be restarted` 0.

## Step 8: Finalize PRD — SKIPPED — 2026-08-08T15:06:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes**. `PRD.md` already determined every behavior the implementation exhibits at every site the tests exercised, so there is no `<step_7_diff>` to patch against. No `PRD_FINALIZED.md` is produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-08T15:26:00.000Z

`PRD_COMPLETED.md` is complete and verified: same section structure, same final section (§5 error catalogue), all markdown tables intact.

### Counts
| | |
|---|---|
| `PRD.md` | 749 lines / 139,823 chars |
| `PRD_COMPLETED.md` | 753 lines / 162,193 chars (**+4 lines, +22,370 chars**, 62 diff hunks) |
| Ambiguity-pins | 41 |
| Mismatch-revisions | **28 (most yet — prior max 18 on task_0924)** |

### Changes

**§2 — global contract**
- §2.1 — revise — mismatch — Traveler membership is not applied on `GET /orders` or `GET /appointments` (both return every row); membership ignores `readiness_status` and follows `order_id` after a split — `validation.py:71`, `order_routes.py:117`, `appointment_routes.py:76`
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the logical clock — `envelope.py:16`
- §2.2 — insert — ambiguity — absent/non-object body treated as `{}` — `validation.py:29`
- §2.3 — insert — ambiguity — the exact accepted filter set per list endpoint; unknown query params ignored; four lists accept none — all `routes/*`
- §2.5 — insert — ambiguity — every business-minute count uses the order consulate's closure calendar — `services/sla.py:29,44,77`
- §2.7 — insert — mismatch — a custody event's `leg_index` is consulted by no gate — `services/custody.py:29`
- §2.9 r4 — revise — ambiguity — the "no slot for `doc_type`" case fires only for a declared member; off-enum falls to rung 7 — `document_routes.py:44`
- §2.9 r9 — revise — mismatch — dispatch and complete are the only rung-9 exemptions — `validation.py:332`
- §2.9 r12 — revise — ambiguity — a null `quoted_by_user_id` passes unconditionally — `order_ops_routes.py:35`
- §2.9 r35 — revise — ambiguity — business day *at the order's consulate* — `order_ops_routes.py:45`
- §2.9.2 — insert — ambiguity — publish's rung-10 admitted state is `DRAFT`; the higher-`ACTIVE` guard is also `ERR_INVALID_STATE`; quote's "no counted traveller" is rung 10 — `config_routes.py:169`, `order_routes.py:243`
- §2.9.2 — revise — mismatch — six endpoints (not two) carry no rung-10 gate — `routes/*`
- §2.9.4 — revise — mismatch — "first delivery attempt" = `delivery_status` `CREATED`; submission has no custody test — `shipment_routes.py:112`
- §2.9.5 — revise — mismatch — slot `status` is **not** equivalent to the closure test: a weekend slot reads `OPEN`/`FULL` yet is refused — `services/slots.py:10` vs `calendar_util.py:21`
- §2.10 general rule — insert — ambiguity — `accepted_doc_count` also earns the applicant bump; the order is bumped at most once per request — `services/readiness.py:55`
- §2.10 closure row — revise — mismatch — consulate bumped only on a genuinely new date; slots only when status moves — `config_routes.py:236`, `slots.py:19`
- §2.10 accept-quote row — revise — mismatch — `accepted_doc_count` change bumps; `WITHDRAWN` skipped — `readiness.py:57`
- §2.10 travel-dates row — revise — mismatch — the Order is bumped unconditionally — `order_routes.py:378`
- §2.10 split row — revise — mismatch — the closing readiness/gate work is version-silent; child forced back to v1 — `order_ops_routes.py:139`
- §2.10 cancel row — revise — mismatch — legs cancelled only from `INTAKE`/`READY_FOR_SUBMISSION` — `order_ops_routes.py:175`
- §2.10 prepare-form row — revise — mismatch — every non-`VOID` prior preparation of that `form_code` is superseded — `document_routes.py:294`
- §2.10 dispatch / agency-decision rows — revise — ambiguity — exactly one order bump — `courier_routes.py:87`, `rfe_routes.py:177`
- §2.10 complete-leg row — revise — mismatch — a `FAILED` outcome recomputes no readiness — `courier_routes.py:113`
- §2.12 — revise — ambiguity — `observed_actual` echoes the stored `effective_submission_date`; `agency_turnaround_days` is always the full figure; the requirement read's type lists come from the slots in creation order — `projection.py:57`, `order_routes.py:221`

**§3 — workflows**
- §3.1 — insert — mismatch — `destination_country` never compared with the consulate's
- §3.2 — insert — ambiguity — both publish preconditions are `ERR_INVALID_STATE`; response is the published revision — `config_routes.py:169`
- §3.2 Hop 4 — insert — ambiguity — the regression also clears `acknowledged_by_user_id` — `cascade.py:54`
- §3.3 — insert — mismatch — region exclusivity is unenforced — `config_routes.py:193`
- §3.3 — insert — ambiguity — a duplicate closure date is a total no-op; `closure_dates` kept sorted ascending — `config_routes.py:236`
- §3.3 — revise — mismatch — slot `status` derivation ignores the weekday; derived at publication — `slots.py:10`, `config_routes.py:262`
- §3.4 — insert — mismatch — `delivery_region_code` is consulted by nothing; shipments never default from it
- §3.5 — insert — ambiguity — `promo_discount_pct` ≥ 0, no upper bound; quoting refreshes `applicant_count` — `order_routes.py:239`, `pricing.py:61`
- §3.5 — revise — ambiguity — the pre-intake re-quote overwrites discount/waiver, re-derives `payment_status` and re-runs the projection — `order_routes.py:332`
- §3.6 — revise — ambiguity — a payment answers **201** with the `LedgerEntry` — `order_routes.py:302`
- §3.7 — insert — ambiguity — `WITHDRAWN` rows are skipped by every recomputation — `readiness.py:57`
- §3.7 — insert — ambiguity — a `VALID_BEYOND_RETURN_MONTHS` slot with a null `expiry_date` fails — `document_routes.py:91`
- §3.7 — insert — ambiguity — `head_height_ratio` rounded half up to 2 dp before the bounds test — `document_routes.py:217`
- §3.7 — revise — ambiguity — both `filled_field_count` bounds enforced, both `ERR_VALIDATION` at rung 6 — `document_routes.py:279`
- §3.7 — revise — mismatch — supersede covers `SIGNED` and *all* prior non-`VOID` preparations — `document_routes.py:294`
- §3.7 — insert — ambiguity — signing a superseded revision is `ERR_INVALID_STATE` — `document_routes.py:334`
- §3.7 — insert — ambiguity — a null `consulate_id` fails the jurisdiction check for every slot — `appointment_routes.py:34`
- §3.8 — insert — ambiguity — leg creation is unguarded: `leg_index` not unique, no custody/calendar/workflow test — `courier_routes.py:26`
- §3.8 — revise — mismatch — rung 9 exempts dispatch/complete; the two dispatch workflow preconditions are enforced by nothing — `validation.py:332`, `courier_routes.py:58`
- §3.8 — revise — mismatch — cancellation cancels `CREATED` **or** `FAILED` hops — `cascade.py:81`
- §3.8 — revise — mismatch — `DELIVERED` recomputes readiness whatever the `to_holder`; `FAILED` only re-evaluates the gate — `courier_routes.py:103`
- §3.9 — insert — ambiguity — the readiness gate is vacuously satisfied with no counted traveller — `readiness.py:85`
- §3.9 — revise — mismatch — submission performs no custody test at all — `order_ops_routes.py:27`
- §3.9 — insert — ambiguity — submission re-runs no projection and no readiness; a zero service fee writes no `EARN` row — `order_ops_routes.py:54`, `money.py:20`
- §3.10 — revise — mismatch — tender's `tendered_at`-null precondition is unchecked — `order_ops_routes.py:212`
- §3.10 — revise — ambiguity — early `EXPIRED` is `ERR_INVALID_STATE`; every adjudication answers with the RFE; abandonment withdraws nobody — `rfe_routes.py:94,113`
- §3.11 — insert — ambiguity — an outstanding RFE refuses the decision with `ERR_INVALID_STATE`; rejection drives `applicant_count` to 0 — `rfe_routes.py:156,176`
- §3.11 — revise — ambiguity — pre-tender rows in `GOVERNMENT`-then-`SERVICE` order, always `CANCELLATION_REFUND`; a zero total moves nothing — `money.py:170`
- §3.11 — revise — ambiguity — every post-tender disbursement carries `REJECTION_REFUND`; the two landing conditions — `money.py:196`, `courier_routes.py:107`
- §3.11 — insert — ambiguity — the escalation day count is signed (a past travel date escalates) — `shipment_routes.py:46`
- §3.11 — revise — ambiguity — `signature_captured` present-but-false fails, at rung 6 — `shipment_routes.py:96`
- §3.11 — revise — mismatch — the direct `SERVICE → APPLICANT` edge on a first-attempt success — `shipment_routes.py:120`
- §3.11 — insert — ambiguity — completion sets `REFUNDED` when both figures are 0 — `shipment_routes.py:25`
- §3.12 — revise — ambiguity — moved count is **distinct** ids; pre-move count refreshed first — `order_ops_routes.py:92`
- §3.12 — revise — mismatch — split admin fee is `min(1500, outstanding after transfer)` — `order_ops_routes.py:129`
- §3.12 — revise — mismatch — `furthest_stage_reached` can rise on either order, and that is the one way a split moves the parent's `workflow_status` — `order_ops_routes.py:139`
- §3.12 — revise — mismatch — both roles cancel at every stage; the `custody != AGENCY` precondition is unenforced; rung 38 keys on custody not workflow — `order_ops_routes.py:153`
- §3.12 — revise — mismatch — traveller withdrawal on every cancellation; `applicant_count` → 0 — `order_ops_routes.py:171`
- §4 — revise — ambiguity — the exact sixteen-endpoint 201 set — `routes/common.py:37`

### The 16 friction points, as pinned
1. **Terminal-order return dispatch vs rung 9** → the custody axis wins; dispatch + complete are the only two rung-9 exemptions (`validation.py:332`).
2. **Which courier legs a cancellation cancels** → `CREATED` or `FAILED`; `DISPATCHED` left alone (`cascade.py:81`).
3. **`SERVICE → APPLICANT` on first-attempt delivery** → the direct edge stands; no intervening `COURIER` row; the `leg_index` precondition is enforced nowhere (`shipment_routes.py:120`).
4. **Split admin fee** → `min(1500, outstanding after transfer)`, skipped at 0 (`order_ops_routes.py:129`).
5. **Traveller withdrawal on an at-agency cancellation** → applies to every cancellation at every stage (`order_ops_routes.py:171`).
6. **`signature_captured` present-but-false** → fails identically to absent; only literal `true` passes; rung 6 (`shipment_routes.py:100`).
7. **`outstanding_cents` under a refund** → the pinned draw waterfall governs (already pinned in §2.11; confirmed against `money.py:95`).
8. **Feasibility read persistence** → pure read (already pinned; the echoed-field detail under `observed_actual` newly pinned).
9. **Submission's `custody_holder == SERVICE`** → the rung list governs; submission reads `custody_holder` nowhere (`order_ops_routes.py:27`).
10. **Pre-intake re-quote and the promo** → promo treated as 0.00, discount and waiver overwritten (`order_routes.py:336`).
11. **`filled_field_count`'s lower bound** → both bounds enforced, both `ERR_VALIDATION` at rung 6 (`document_routes.py:279`).
12. **Cancellation actor role list** → the operation's list governs; a `Traveler` may cancel from all six states (`order_ops_routes.py:153`).
13. **Four transition preconditions with no error code** → the two dispatch workflow gates, tender's `tendered_at`-null, and cancellation's `custody != AGENCY` — all four named as unenforced (§3.8, §3.10, §3.12).
14. **Off-enum filter values** → empty page (already pinned; the per-endpoint filter set newly enumerated).
15. **Which order the split returns** → the new child, 201 (already pinned; reinforced in §4).
16. **Refund reason on post-tender disbursement** → always `REJECTION_REFUND`; `CANCELLATION_REFUND` belongs to immediate pre-tender rows alone (`money.py:196`).

### Orchestrator independent verification (Step 9)
749 → 753 lines; `PRD_COMPLETED.md` ends at the same final error-table row as `PRD.md`; `diff` of all `^#` headers between the two files is **empty** (no sections added or removed, per the "never add new sections" rule); `find implementation test_suite test_helpers -newer results.1.json` still **empty** — the green 87/87×8 result describes the shipped tree unchanged.

## Extra pass: friction cross-check audit (read-only) — 2026-08-08T15:26:00.000Z

Run to close the caveat Step 7 raised — that "no test asserts on an un-adjudicated friction" was evidenced only by the absence of failures, never by a positive check. A test asserting on one of the 16 frictions would pass here only by agreeing with *this* implementation's adjudication, and a different faithful implementer would fail it: latent unfairness. **All 87 tests were read in full** (all 12 files end-to-end plus every fixture chain they invoke); grep was used only to corroborate negatives.

**Verdict: 0 tests depend on a friction. The suite is fair as it stands — nothing needs deleting.**

Per-friction: **CLEAN** for 1, 2, 3, 5, 6, 9, 11, 12, 13 (all four sub-cases), 14, 16. **AGREEMENT-BY-CONSTRUCTION** for 4, 7, 8, 10. **Friction 15** (which order the split returns) is the one friction a test's assertions are genuinely sensitive to — `test_11::test_split_partitions_both_streams_and_conserves_money_across_the_pair` would outright fail under the parent-returning reading — but it is **fair**, because PRD §3.12 line 609 states flatly "The response is the newly created child order" with no competing statement; the ambiguity survives only in `SCAFFOLD.yaml`, which implementers never read. The generator also dodged the adjacent 200-vs-201 question by using the status-lenient `get_success_data`.

**Both claimed agreement-by-construction cases verified by arithmetic:**
- *Split admin fee (4):* parent 3 travellers fully collected at 68250; moving 1 of 3 transfers 16000 gov + 6750 svc = 22750, leaving `outstanding_cents = 45500`; `min(1500, 45500) = 1500` = flat 1500. Both readings assert the same `service_earned_cents == 1500` / `outstanding_cents == 44000`.
- *Refund outstanding (7):* pre-tender cancel at INTAKE, collected 68250, outstanding 68250, `service_earned 0`. Refund = 48000 + `round_half_up(20250 × 0.75) = 15188` = 63188. Waterfall: gov draws `min(48000, 68250)` → 20250; svc draws `min(15188, 20250)` → 5062, remainder 0 both legs. Plain subtraction: `68250 − 63188 = 5062`. Identical, because the refund never exceeds outstanding.

**Six near-misses recorded** — fair only by an incidental fixture value, and worth knowing for future design:
- **A (friction 9) — the thinnest margin in the suite.** `test_08::test_submission_from_intake_reports_incompleteness_not_a_state_error` submits with `custody_holder == APPLICANT`. Fair only because §2.9.2 pins rung 10's admitted set to `workflow_status` alone and explicitly forbids masking rung 34. An implementer reading §3.9's "also requires `custody_holder` to be `SERVICE`" as a rung-10 clause returns `ERR_INVALID_STATE` and fails it.
- **B (7):** fair only because refund 63188 < outstanding 68250. Driving the order past submission (which writes an `EARN` row shrinking outstanding) makes the two readings diverge immediately.
- **C (4):** fair only because post-transfer outstanding 45500 ≫ 1500. A partially-paid parent or a larger moved fraction splits min-of from flat.
- **D (10):** fair only because the order carries one traveller quoted with no promo (both readings give 0.00). Three travellers with `promo_discount_pct=0.05` would diverge (0.10 vs 0.15) into a different waiver verdict and total.
- **E (13d):** `test_01::_scenario_ready_with_a_second_undispatched_hop` builds a `SERVICE → AGENCY` leg at `READY_FOR_SUBMISSION` and stops one call short of dispatching it; a single added `dispatch_leg` would split the readings.
- **F (2):** `test_10::test_cancelling_from_agency_custody…` is fair only because it never lists legs; adding a `list_legs` assertion after that cancel would expose both the leg-scope question and whether the freshly created return hop is itself cancelled.


