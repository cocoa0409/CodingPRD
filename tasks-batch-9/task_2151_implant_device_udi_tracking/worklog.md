# Worklog — task_2151_implant_device_udi_tracking

## Step 1: Create task directory — 2026-08-24T14:33:19.000Z

Created `tasks/task_2151_implant_device_udi_tracking/` and `tasks/task_2151_implant_device_udi_tracking/workspace/`. Index 2151 = max existing (2150) + 1.

## Step 3: Copy shared files — 2026-08-24T14:33:42.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2151_implant_device_udi_tracking/workspace/INSTRUCTION.md` (1424 bytes). (Done ahead of Step 2's completion; no dependency.)

## Step 2: Generate scaffold — 2026-08-24T15:26:30.000Z

All three scaffold artifacts are generated and pass the skill's linter cleanly.

## Files

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2151_implant_device_udi_tracking/SCAFFOLD.yaml` | 2648 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2151_implant_device_udi_tracking/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2319 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2151_implant_device_udi_tracking/SCAFFOLD_CORNER_DESIGN.yaml` | 3859 |

## Scaffold surface (§1.0–§1.7)

- **Profile**: `compliance_audit` × `ledger_reconciliation`; topology `graph` (self-referential `DeviceUnit.replaced_unit_id`, two three-way junctions); shape `parallel`; role model `segregation_of_duties`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint. Level: expert-plus.
- **14 entities**: Vendor, ConsignmentAgreement, CatalogItem, Lot, DeviceUnit, Patient, SurgicalCase, ImplantRecord, ChargeCapture, RegistrySubmission, FieldAction, RecallNotification, VendorInvoice, ExplantRecord (24 FKs, all reverse-reachable).
- **11 state machines** — DeviceUnit carries two independent dimensions (`custody_state` 10 states × `billing_state` 6 states) on one row; cycles on ImplantRecord (VERIFIED<->AMENDED), RegistrySubmission (SUBMITTED<->REJECTED), VendorInvoice (VARIANCE_HOLD->DISPUTED->SUBMITTED); compound Lot/FieldAction; forked SurgicalCase cancel with divergent side-effect sets.
- **3 concurrency rules** (OCC only): stale SurgicalCase / Lot / ConsignmentAgreement versions -> 412.
- **11 calculations**, **31 validations** (single strict precedence ladder), **72 endpoints** (71 business + one `/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default), **49 errors**, **6 roles** (5 opaque + `entity_backed:Vendor`), 3 X-User-ID-keyed separations of duties.

## §1.8 — 22 instances across all 9 rule ids

`dual_variant_calc` 2 · `combinatorial_formula` 2 · `non_linear_state_machine` 2 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 3 · `boundary_precision_check` 3 · `cross_entity_state_dependency` 3 · `resource_temporal_overlap` 2 · `compensating_invariant` 3.

Every money literal was computed by executing the §1.3 formulas in Python (e.g. provisional 1 512 800 vs final 610 500, variance 902 300; round-per-line 174 059 vs sum-then-round 174 058; PERIOD_TRUEUP 950 000 vs UNIT_MATCH 925 000 at 263 bps; gross-keyed credit cap giving net 1 300 000 vs the circular reading's 2 145 000).

## §1.9 — 58 instances (49 with recipes + 9 `excluded_because` stubs)

`entities` 10 · `state_machines` 11 · `calculations` 7 · `validations` 10 · `endpoints` 2 · `errors` 11 (2 not-found sweeps + 9 stubs) · `rbac` 3 · `cross_cutting_layers` 3 · `consistency_model` 1.

## Verification

- `scaffold_lint.py` verdict, verbatim:
  `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (72 endpoints, 14 entities, 22 + 49 instances, 921 calls scanned)
- Additional audits I ran: zero unbound `${var}` across 921 calls; 80 instance names unique across both files; all 49 error ids referenced; no dangling `grounds` refs (calculations / validations / entity fields / state machines / concurrency rules / errors); all 3 OCC endpoints declare their `expected_*_version` input and a version bump; no forbidden concurrency vocabulary; neither design key appears inside `SCAFFOLD.yaml`.

One design decision worth flagging: I swapped validation priorities 15/16 (lot-not-released now precedes unit-custody-state) because `ERR_LOT_NOT_RELEASED` was otherwise unreachable — a quarantined unit always trips the custody check first. No sibling task directories were read.

## Step 4: Generate PRD — 2026-08-24T15:39:00.000Z

Done. PRD written incrementally in six appends (no single Write exceeded a few thousand tokens), and neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2151_implant_device_udi_tracking/workspace/PRD.md` — 491 lines, ends at §5 Error Code Catalogue with no audit footer.

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 RBAC · 2.2 API Response Structure (verbatim, byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Nested Paths and the Validation Precedence Ladder · 2.7 Optimistic Concurrency · 2.8 Segregation of Duties · 2.9 Money, Rounding and the Cents Discipline · 2.10 Two Independent State Dimensions · 2.11 Conserved Quantities · 2.12 Derived Counters and Cascade Semantics
- §3 Business Logic — 3.1 Vendors/Consignment Terms/Catalog · 3.2 Receiving and the Quarantine Gate · 3.3 Patients and the Two Schedule Geometries · 3.4 FEFO Reservation and the Round Trip · 3.5 Documentation/Verification/Amendment · 3.6 Charge Capture Accuracy · 3.7 Registry Submission and Adjudication · 3.8 Field Actions, Exposure and Outreach · 3.9 Explantation, Return and Vendor Credit · 3.10 Consignment Reconciliation and Vendor Billing · 3.11 Case Closure Readiness and the Operational Checkpoint
- §4 Endpoint Definitions (4 columns) · §5 Error Code Catalogue (2 columns)

**Verified coverage counts**
- 14 entities: all present, all 118 `entities[].fields[].name` in backticks
- 11 state machines / 73 transitions: every `from`/`to` state string present; every precondition paired with its error and every side-effect stated, including both branches of all forks (implant from `RESERVED` vs `AVAILABLE`, cancel from `SCHEDULED` vs `IN_PROGRESS`, finalize to `FINALIZED` vs `CORRECTION_REQUIRED`, match to `MATCHED` vs `VARIANCE_HOLD`, disposition return vs local disposal, credit issued vs denied)
- 11 calculations: all expressed as prose with pinned evaluation/rounding order; all 30 `constants` embedded in business context
- 31 validations: full priority-ordered ladder in §2.6 plus per-workflow restatement; each `applies_to` scope enumerated
- 72 endpoints: 72 table rows, generated directly from the scaffold
- 49 errors: 49 table rows; every `error_id` also referenced in §2/§3 narrative
- 6 roles: all named with exact spelling; five `opaque` identities and the `entity_backed:Vendor` identity of `VendorRep` translated into explicit ownership prose

**Hard contracts**

Field coverage check: entities[].fields 118/118; endpoints[].request_body 65/65; query_params 22/22; path_params 14/14; computed response-shape fields 20/20 (two independent passes, both clean). Status: PASS

Rule coverage check: validations[] with priority 31/31; concurrency_rules[] OCC rejections 3/3 (write_endpoint + expected_<parent>_version + error_id + 412 all named); state_machines[].transitions 73/73; calculations[] 11/11; validations[] conditions 31/31 matchable to error_id; endpoints[].side_effects / applies_to 72/72; entities[].fields[] structured content 118/118 reconstructible; sibling-branch symmetry 9/9 fork groups with equal prose density, 0 asymmetric. Status: PASS

Path purity check (§3 only): 946 backtick tokens scanned; 0 starting with `/`; 0 bare HTTP-method tokens; 0 method+path combined tokens. Status: PASS

Two gaps the audit caught and closed: the `AVAILABLE → DEPLETED` lot auto-transition was scoped only to the waste path and is now generalized in §2.11 to every recomputation of `on_hand_qty`; and validation priority 19 now enumerates each uniqueness scope against its specific duplicate code rather than naming the three codes generically. No fuzzy/approximating language and no pseudocode operators survive anywhere in the prose.

**Orchestrator verification:** `wc -l` reports 490 lines; file tail ends mid-error-catalogue table with `ERR_CREDIT_EXCEEDS_EXPECTED` — final section present, no truncation.

## Step 6: Generate implementation — 2026-08-24T16:05:00.000Z

Implementation is complete and verified.

## File tree (lines)

```
workspace/implementation/
  start.sh                 10   guarded pip install + exec python3 app.py
  requirements.txt          1
  app.py                   66   blueprint registration, envelope error handlers
  store.py                198   in-memory dicts, logical clock, id/version/touch
  errors.py               104   49-code catalog + path-param -> not-found map
  envelope.py              32   meta/response_type/data + pagination meta
  validation.py           189   ladder step 3 (shape, enums, ranges, pagination)
  auth.py                  75   ladder steps 1-2 (headers, six roles, VendorRep)
  resolve.py               39   ladder steps 4-5 (left-to-right existence)
  graph.py                125   entity-graph navigation
  calc.py                 315   calculations C1-C9 + all constants
  derive.py               197   C6/C7/C10, cascades, custody/billing setters
  serialize.py            240   14 resource payloads
  routes/master.py        225   clock, vendors, agreements, catalog items
  routes/inventory.py     284   lots, device units, quarantine gate, waste
  routes/clinical.py      341   patients, OR schedule, reservations, case lifecycle
  routes/records.py       294   implant documentation, verify, amend, explant
  routes/revenue.py       416   charge capture, vendor invoices
  routes/compliance.py    407   registry, field actions, recall notifications
  routes/explants.py      143   disposition, ship, credit
  routes/ops.py           125   C11 ops-run checkpoint
                        -----
                         3815   Python total
```

## Coverage

- **Endpoints: 72/72** — enumerated from the live URL map, exactly matching §1.5 (1 clock + 71 `/udi` routes).
- **Validation ladder: 31/31 priorities** implemented in strict ascending order per handler; PRD §2.6 orderings honoured literally (recall before expiry; `ERR_LOT_NOT_RELEASED` deliberately before the unit-custody check; close-gate mapping 24->25->30 mirroring the readiness derivation).
- **Calculations: 11/11** — C1 charge pricing (per-unit round *then* quantity multiply, cap after), C2 UNIT_MATCH/PERIOD_TRUEUP (per-item average rounded before multiply), C3 completeness with partial credit + recall penalty + clamp, C4 FEFO with the three non-id tie-breaks, C5 exposure cohort (SERIAL_RANGE inclusive both ends), C6 vendor liability, C7 lot conservation + auto-depletion, C8 settlement waterfall (tier keyed on gross only), C9 return credit tiers, C10 first-match-wins readiness, C11 five ops-run rules in order.
- **State machines: 11/11** — DeviceUnit `custody_state` and `billing_state` as independent dimensions, plus Lot, SurgicalCase, ImplantRecord, ChargeCapture, RegistrySubmission, FieldAction, RecallNotification, VendorInvoice, ExplantRecord.
- **Errors: 49/49** wired (verified programmatically — no unreferenced code).

## Launcher and boot

`bash start.sh` was run for real on `PORT=10731`: `ss -ltn` shows `LISTEN 0.0.0.0:10731`, the script `exec`s the server in the foreground, and the pip install is guarded by `python3 -c "import flask"` so per-test reboots skip it. A fresh boot holds **zero entity data** — all fourteen list endpoints returned `total_count=0`; there is no seed/preload code, no SQLite, no JSON dump, no `/tmp` cache (audited by grep).

## Verification

Three smoke suites (~180 assertions) ran green against the app: full happy path (receive -> release -> FEFO reserve -> document -> verify -> registry -> charge post/finalize/correct -> close -> invoice match/approve), the advanced path (PERIOD_TRUEUP variance -> VARIANCE_HOLD -> dispute -> resubmit -> approve; explant -> RA -> ship -> credit with liability conservation checked before/after; CLASS_I publish cascade with vendor HOLD, RECALL_HOLD, notifications, close restoring ACTIVE; ops-run expiry sweep detaching a reservation), and edge cases (SoD on all three pairs, OCC 412 on all three parents, both interval geometries including the touching-endpoint asymmetry, auto-depletion, EXEMPT-on-DECLINED, completeness 75->100 after consent change, resubmission_count, amend dragging SUBMITTED->REQUIRED, escalation to UNREACHABLE at level 2, ladder-order probes for shape-before-path and path-before-body).

Two judgement calls worth flagging: `created_at`/`updated_at` use wall-clock (PRD §2.4 explicitly separates them from the logical-clock business stamps), and logical-clock-derived stamps are rendered in the same fractional-second style as the instant they were measured from, so a clock set as `2026-08-01T00:00:00Z` reads back byte-identical everywhere it is stamped.

## Step 5: Generate unit tests — 2026-08-24T16:33:00.000Z

Generation complete for `/home/ubuntu/github/CodingPRD/tasks/task_2151_implant_device_udi_tracking/`.

## Files written

**`test_helpers/` (2,490 lines)**
| file | lines |
|---|---|
| `types.py` | 447 |
| `api_client.py` | 356 — one method per each of the 72 endpoints |
| `api_errors.py` | 137 — all 49 error ids, registered with the framework status map |
| `assertions.py` | 335 — 14 entity assertions + conservation/envelope/readiness/ops-run invariants |
| `factories.py` | 151 |
| `constants.py` | 91 |
| `test_users.py` | 90 — opaque role constants (two ids per role for the SoD pairs) + `make_vendor_rep_headers` for the entity-backed role |
| `fixtures.py` | 834 — Tier 1-5 composites |
| `__init__.py` | 49 |

**`test_suite/` (4,556 lines, 93 tests)** — `conftest.py` plus 11 domain-named modules (`test_01_receiving_and_catalog` ... `test_11_platform_auth_and_errors`).

## Instance-to-test mapping

- **Queue A (difficulty):** 22/22 instances translated, every one with **>=2** tagged tests (44 tests). Zero shortfalls.
- **Queue B (corner):** 49/49 non-stub instances translated, each with >=1 tagged test (49 tests). The 9 `excluded_because:` stubs were **not** translated; all 9 `difficulty_instance` cross-references were verified to resolve.
- 93 tests total, 0 untagged, 0 dual-tagged, 0 tags pointing at a non-existent or stub instance, 0 `skip`/`skipif`/`xfail`.
- **203 PRD citations** machine-checked: every quoted sentence survives a whitespace-normalised literal match against `workspace/PRD.md`.
- `pytest --collect-only` collects all 93 cleanly; no undefined names (pyflakes); no "scaffold"/§1.x leakage in generated code.

## Instances SKIPPED

**None** — all 71 non-stub instances produced at least the required number of tests.

Two **sub-assertions were dropped** (the instance still got its test) because they failed unique derivability:

1. `Corner/entities/device_unit_computed_and_system_fields_are_not_client_settable` — dropped *"a payload key `custody_state` returns ERR_INVALID_REQUEST (400)"*. PRD §2.6 step 3 enumerates the request-shape checks (required fields, enum members, integer ranges, interval ordering, selector exclusivity, scope fields, pagination) and never says an **undeclared extra body key** is rejected; a faithful PRD-only implementer could equally ignore it. The instance's actual claim is still asserted — the created serial comes back `QUARANTINED` / `NOT_BILLABLE` / `OWNED` with `udi_di_snapshot` copied from the catalog and all six nullable system fields null, per §3.2.

2. `Corner/calculations/recall_serial_range_scope_is_inclusive_on_both_ends` — dropped *"SN-0003 stays AVAILABLE"*. PRD §3.8 states the lot cascade as *"Each lot moving to `RECALLED` in turn moves **each of its units** in `QUARANTINED`, `AVAILABLE` or `RESERVED` to `RECALL_HOLD`"*, which a literal PRD-only reader applies to the out-of-range serial as well; the design index's narrower reading is not uniquely derivable. Inclusivity of both range ends is still proven by `on_hand_cohort_size == 2` (exclusive readings give 0 or 1) plus both endpoint serials landing in `RECALL_HOLD`, and `Lot.on_hand_qty == 3` holds under either reading.

## Step 7: Test and iterate to green — 2026-08-24T16:44:00.000Z

Clean 8-round sweep achieved. Final state: **93/93 passing in all 8 parallel rounds, zero failures, zero errors.**

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each).
- Sweep 1: 89/93 in all 8 rounds — 4 failures, perfectly reproducible (not flaky).
- Sweep 2: 93/93 in all 8 rounds.

**Tests deleted:** none. All 4 failures passed STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability); every one resolved at STEP 2 as a test-artifact bug.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_matched_invoice()`: changed signature to `(submitted_total_cents, *args, **kwargs)` so it forwards the positional `unit_costs` argument of `setup_submitted_invoice()` verbatim. The two callers in `test_08` passed `unit_costs` positionally and died with `TypeError: takes 1 positional argument but 2 were given` before ever reaching the server. Pure plumbing bug, no PRD implication.

**Fixes applied to `test_suite/`:**
- `test_06_field_actions_and_recall.py` — `TestSeverityAndScope::test_serial_range_scope_captures_both_endpoint_serials`: `exposure["on_hand_cohort_size"]` corrected `2 -> 0`.
- `test_06_field_actions_and_recall.py` — `TestExposureRead::test_exposure_read_recomputes_the_cohort_and_names_the_patients`: `exposure["on_hand_cohort_size"]` corrected `1 -> 0`.

  Both asserted the *pre-publish* on-hand cohort against a *post-publish* read. PRD §3.8 fixes this uniquely in two sentences: the exposure endpoint "recomputes the exposure cohort from scratch", and "the on-hand cohort is those units whose `custody_state` is `QUARANTINED`, `AVAILABLE` or `RESERVED`" — an exhaustive list that excludes `RECALL_HOLD`, which is exactly where publication's four-hop cascade has just put those units. Verified live: publish correctly reports `on_hand_cohort_size` 2 and 1 respectively; the subsequent recompute correctly reports 0. The corrected values are strictly *more* discriminating — an implementation that echoed the stored cohort size instead of recomputing now fails these tests, whereas before it would have passed.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on all four failures; no check was removed or weakened.

**One caution flagged by the subagent:** early on it ran a broad `pkill -f "app.py"`, which self-matched and killed its own shell — but it may also have terminated in-flight API servers belonging to the `task_2148_water_taxi_harbor_shuttle` pipeline running concurrently on this host. That pipeline uses `--isolation per-test-server`, and it went on to write all 8 of its own results files at 16:15, so it appears unaffected — but if its round 1 shows an unexplained boot-related failure around 16:11, that is the likely cause and worth a rerun. Broad `pkill` was avoided for the rest of the session.

## Step 8: Finalize PRD — 2026-08-24T16:47:00.000Z

**Result: zero PRD edits.** `workspace/PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`.

**Line counts:** PRD.md 490 -> PRD_FINALIZED.md 490. Delta: 0 lines, 0.00%.

**Change bullets:** none.

**Why each `<step_7_diff>` item produced no edit:**

1. `test_helpers/fixtures.py` — `setup_matched_invoice()` signature. Verified at `test_helpers/fixtures.py:738-746`: the fix is a pure `*args` forwarding change so the positional `unit_costs` reaches `setup_submitted_invoice`. The two `test_08` callers died with `TypeError` inside the test process, before any HTTP request. No server behavior was ever observed, so nothing about the implementation was pinned or contradicted. No PRD implication.

2. & 3. `test_06` — `exposure["on_hand_cohort_size"]` corrected `2 -> 0` and `1 -> 0`. Step 7's conclusion holds: **PRD §3.8 already determines this uniquely**, and the prose is left verbatim. Two sentences do the work together — the exposure endpoint "recomputes the exposure cohort from scratch", and "the on-hand cohort is those units whose `custody_state` is `QUARANTINED`, `AVAILABLE` or `RESERVED`". That list is exhaustive and excludes `RECALL_HOLD`, which is exactly where the publish cascade has just moved those units. The implementation matches: `implementation/routes/compliance.py:334-352` calls `recall_exposure_cohort(action)` live rather than echoing the stored counters, and `implementation/calc.py:252-270` filters on-hand strictly to the three listed custody states. Both tests were asserting a pre-publish value against a post-publish read — a test artifact, not PRD silence.

**Pre-edit search log:** not applicable — no edits were committed, so no NO-NEW-MISMATCH search was triggered. For completeness, the verification reads performed while deciding not to edit were: `implementation/calc.py` (`recall_exposure_cohort`, `unit_in_action_scope`, `lot_in_action_scope`, `explant_return_credit`, `net_consignment_settlement`), `implementation/routes/compliance.py` (draft, publish four-hop cascade, close, exposure read, list/get), and the two corrected tests in `test_suite/test_06_field_actions_and_recall.py`. The publish path (`compliance.py:216-222`) and the exposure path (`compliance.py:336-338`) call the *same* cohort helper, which is why the same PRD sentence covers both without either needing re-scoping.

**Orchestrator verification:** `diff -q PRD.md PRD_FINALIZED.md` reports no differences — byte-identical confirmed.

## Step 9: Complete PRD — 2026-08-24T16:57:00.000Z

`workspace/PRD_COMPLETED.md` is written. Same 490 lines, same 28 headings and 125 table rows — every change is an in-paragraph insert or revision on an existing line; no sections, paragraphs, or table rows added.

**Counts** — source 490 lines / 102,027 chars -> completed 490 lines / 108,586 chars (+6,559 chars) across 26 touched lines carrying **29 changes: 26 ambiguity-pins, 3 mismatch-revisions.**

**Changes**

- §2.3 Pagination — insert — ambiguity — an unparseable `limit`/`offset` is `ERR_INVALID_REQUEST`; an empty-string value takes the default — validation.py:135-152
- §2.3 Pagination — revise — ambiguity — `created_at` ties fall back to server creation order — store.py:196
- §2.3 Filters — insert — ambiguity — undeclared enum filter value -> 400; empty-string filter ignored; unknown query params ignored — validation.py:161-172
- §2.4 Stored record — insert — **mismatch** — `version` advances at most once per row per request, and a re-derivation counts as a mutation even when the value is unchanged — store.py:158-179
- §2.4 Timestamps — insert — ambiguity — client-supplied instants stored/echoed verbatim, never renormalised — master.py:108-109, clinical.py:162-163, compliance.py:198
- §2.5 Logical clock — insert — ambiguity — `current_utc` echoes the caller's `Z` literal; business stamps carry that rendering verbatim; derived instants match the source's fractional style — store.py:83-93,138-150
- §2.6 step 3 — insert — ambiguity — optional string fields must be non-empty when supplied, except `override_reason` on approval (blank = absent) — validation.py:37-41, revenue.py:298-299
- §3.2 Unit receipt — insert — ambiguity — optional `consignment_agreement_id` / `replaced_unit_id` resolved in declared order with their own 404s — inventory.py:101-102
- §3.2 Release — insert — ambiguity — empty-lot/quarantine checks (step 8) precede segregation of duties (step 9) — inventory.py:152-160
- §3.2 Waste — insert — ambiguity — waste leaves `billing_state` and the vendor liability alone — inventory.py:282-283
- §3.3 Patient update — insert — ambiguity — both fields optional; version still advances on an empty update — clinical.py:80-88
- §3.4 Release reservation — revise — ambiguity — unit must also be in `custody_state` `RESERVED` — inventory.py:258
- §3.4 Release reservation — revise — ambiguity — a closed/cancelled/aborted holder case yields `ERR_INVALID_CASE_STATE` — inventory.py:262-263
- §3.5 Documentation — insert — ambiguity — supplied `patient_id` resolved at step 5 (`ERR_PATIENT_NOT_FOUND`) before linkage; record's `patient_id` always copied from the case — records.py:68,87-88,108
- §3.6 Charge creation — insert — ambiguity — no record-state precondition; creation re-derives neither case total nor stored readiness — revenue.py:61-87
- §3.6 Posting — insert — ambiguity — the line's own `DRAFT` check runs before the record-status check — revenue.py:117-121
- §3.8 Publish — insert — ambiguity — definition of a *matched* lot per scope type — calc.py:363-374
- §3.8 Publish — revise — ambiguity — the freeze is lot-wide, so out-of-range serials on a matched lot are frozen too — compliance.py:232-237
- §3.8 Close — revise — ambiguity — "attributable to this action" = every `RECALL_HOLD` unit whose lot passes the same scope test — compliance.py:292-298
- §3.8 Close — insert — ambiguity — disposal leaves `billing_state` untouched — compliance.py:298
- §3.8 Exposure read — insert — ambiguity — `implant_record_ids` in `created_at` order, `patient_ids` de-duplicated at first appearance, `notification_open_count` is the stored counter — compliance.py:339-350
- §3.9 Explant — insert — ambiguity — `replacement_device_unit_id` resolved when supplied; no side effect on that serial — records.py:256,269
- §3.9 Credit — insert — ambiguity — negative `credit_issued_cents` is `ERR_INVALID_REQUEST`, not `ERR_CREDIT_EXCEEDS_EXPECTED` — explants.py:121
- §3.10 Match — insert — ambiguity — zero `expected_total_cents`: `variance_bps` is 0 or 10,000,000 — calc.py:262-267
- §3.10 PERIOD_TRUEUP — insert — ambiguity — a catalog item with an empty pool is skipped — calc.py:255-256
- §3.10 Approve — revise — **mismatch** — `override_reason` supplied on a `MATCHED` approval is still recorded (PRD said "ignores one") — revenue.py:321-322
- §3.11 Readiness — revise — **mismatch** — the "re-derived after every mutation … charges" blanket now excepts charge-line creation — revenue.py:61-87
- §3.11 Readiness read — insert — ambiguity — recomputed live at read time, persisting nothing — clinical.py:204-216
- §3.11 Sweep rule 2 — insert — ambiguity — the expiry sweep never touches `billing_state` — ops.py:200-213

**Orchestrator final verification:** PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md all 490 lines; all 8 `results.{1..8}.json` report 93/93.
