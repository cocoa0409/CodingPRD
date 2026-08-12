# Worklog — task_0929_livescan_fingerprinting

Scenario (verbatim from user): `929. Livescan Fingerprinting & Background Service: appointment & service type (agency/ORI), fingerprint capture & quality/reject, submission (state/FBI) & result routing, fee & agency billing, rap-back subscription, mobile/onsite, re-print & rejection, retention`

Difficulty: **beyond-Expert** (user: "generate task hard than expert level!"). Difficulty is a calibration parameter routed into Step 2 only; it does not limit pipeline scope. Full pipeline Steps 1–9 runs to completion.

## Step 1: Create task directory — 2026-08-08T12:26:32.702Z

Created `tasks/task_0929_livescan_fingerprinting/` and `tasks/task_0929_livescan_fingerprinting/workspace/`. Index 0929 chosen as max(existing task_NNNN under tasks/) + 1 = 0928 + 1, matching the user's requested scenario number 929.

## Step 3: Copy shared files — 2026-08-08T12:26:32.702Z

Copied `./INSTRUCTION.md` → `tasks/task_0929_livescan_fingerprinting/workspace/INSTRUCTION.md` (1424 bytes). Run ahead of Step 2 since it has no dependency on the scaffold.

## Step 2: Generate scaffold — 2026-08-08T13:51:00.000Z

All three files are complete and verified. Final state:

## Exit summary — `tasks/task_0929_livescan_fingerprinting/`

**Final counts**

| Dimension | Value |
|---|---|
| Entities | **17** (Agency, Ori, ServiceType, CaptureSite, Device, DeviceAssignment, Applicant, Appointment, FingerprintCard, PositionCapture, Submission, ChrResponse, FitnessDetermination, RapbackSubscription, RapbackNotification, FeeAssessment, Invoice) |
| Endpoints | **73** (all under `/livescan`; 83 declared transitions behind them) |
| State-machine axes | **17 over 15 entities**, **16 non-linear** (6 cyclic, 3 branching+cycle, 5 branching, 1 parallel, 1 parallel+cycle; only CaptureSite.reconciliation is linear). Submission carries 3 independent axes on one row + a derived composite. |
| Calculations | **21**, of which **6 dual-variant** on 6 different entity domains (FeeAssessment rounding/waiver-order, Invoice calendar-vs-business aging, FingerprintCard mean-vs-worst, RapbackSubscription 365d-vs-anniversary, CaptureSite per-event-vs-pro-rata shortfall, Submission reprint-window anchor) |
| Combinatorial modes | (a) composite disposition, (b) fee rounding order, (c) volume-discount tier read-before-add — three different modes |
| Error codes | **38** — every one referenced by a validation/transition **and** by at least one §1.8/§1.9 instance |
| Validation ladder | **40 ordered rungs** with two documented pre-emption carve-outs |
| OCC rules | **3**, on 3 different parents (FingerprintCard, Submission, Agency) |
| Conservation invariants | **4** (TCN allocation ledger, onsite billable prints, fee components/credits, rap-back notification routing) |
| Cascade depth | **6** (purge grant) and **6** (calibration-lapse audit); a third 3-hop chain on invoice aging → agency suspension |
| Declared constants | **40** in `domain_constants`, re-declared in the consuming `calculations[].constants` |
| §1.8 / §1.9 | 9 rules × 2 = **18** instances / **50** corner instances (40 live + 10 `excluded_because` stubs) |

**`yaml.safe_load` result**: all three files parse clean (`python3 -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]"` → no output, exit 0).

**`scaffold_lint.py` verdict block (verbatim)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_0929_livescan_fingerprinting/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_0929_livescan_fingerprinting/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_0929_livescan_fingerprinting/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    73
  §1.1 entities declared:     17
  §1.8 instances scanned:     18
  §1.9 instances scanned:     40
  Calls scanned (§1.8+§1.9):  988

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Undeclared-constant sweep**: scripted extraction of every `ALL_CAPS_WITH_UNDERSCORE` token across all three files, minus enum members / states / error ids → only `ALL_CAPS` (a comment word) and `ERR_XXX` (the fixed §1.0 envelope) remain. **40 declared, 0 undeclared.** Every unit conversion is stated (ORI authority→profile mapping table, walk-in reserve ceiling formula, `walkin_usable_capacity`, TCN root format, datetime rendering rule).

**Self-audit defects found and repaired (19)**

*Graph-unreachable (fixed by reordering wherever possible):*
1. Rung 5 duplicated rung 40's payment-amount check → rung 40 unreachable. Removed the clause from rung 5 with an explicit "that is rung 40".
2. `ERR_RAPBACK_NOT_AUTHORIZED` unreachable — a NOFED ORI can never reach retention GRANTED, so the retention rung always pre-empted. **Reordered** rungs 30/31 (authority now above retention); §1.8 grounds updated.
3. `ERR_RENEWAL_WINDOW_CLOSED` unreachable — generic state rung pre-empted it (renew is declared only from RENEWAL_DUE). Added a named carve-out in rung 10.
4. `ERR_DESTINATION_NOT_AUTHORIZED` unreachable — an FBI result on a STATE_ONLY row hits `fbi_status == NOT_REQUIRED` first. Second named carve-out in rung 10.
5. `ERR_RETENTION_IMMUTABLE` unreachable — scoped to `/reprints`, an endpoint with no retention field. Re-scoped to `POST /livescan/submissions` when the card carries `reprint_of_submission_id` (verb fix).
6. `taint_reason: REPRINT_REPLACEMENT` was a dead enum member (no transition writes it). Removed.
7. `FingerprintCard OPEN→CAPTURING` fired only on a scored attempt, so an exception-only card could never reach the override self-loop. Exception now also opens CAPTURING (`first_capture_at` deliberately stays null there, keeping the taint sweep correct).
8. `RapbackSubscription` could never LAPSE if no read landed inside the renewal window. Added the `ACTIVE→LAPSED` system leg.

*Arithmetically unhittable:*
9. `worst_position_score >= 60` can never fail (PASSED already requires ≥ 60). Swapped which reading is pinned: **mean ≥ 65 governs** (violable at ten×62), worst-position became the documented rejected variant.
10. Retroactive taint was physically impossible (rung 19 blocks captures on an expired device). Gave the audit a `corrected_last_calibrated_at` input that moves the true expiry backwards — captures legal at the time become tainted. Propagated to §1.2/§1.3/§1.5.
11. Tier-1 discount floor 50000 exceeded the maximum single assessment (42467), so the mode-(c) fork needed multi-submission chains. Lowered to 40000.
12. NO_SHOW/ONSITE_SHORTFALL returned before the mtd ledger step, starving the discount tier. They now skip steps 1–4 but still run step 5.

*Chain/replay and contract defects:*
13. `Appointment.no_show_fee_assessment_id` was an FK pointing the wrong way (would have demanded a fee-assessment→appointments reverse GET). Replaced with a boolean; discovery via `GET /livescan/fee-assessments?appointment_id=`.
14. TCN suffix off-by-one (`reprint_count + 1` double-counted) — the first reprint would have taken suffix 2 and exhausted the budget early. Corrected to `next_suffix = original.reprint_count`.
15. Multi-reprint supersede ambiguity — the endpoint unconditionally moved the original card to REJECTED_CLOSED. Pinned as a no-op on later reprints with `superseded_by_card_id` re-pointed at the newest replacement; §1.9 assert corrected `card_r1` → `card_r3`.
16. Free-reprint fee was under-specified (would have re-charged the full statutory fee). Pinned: free reprint zeroes state/federal/processing but keeps vendor fee + tax (**1067**); chargeable reprint totals **7668**.
17. `ERR_CHALLENGE_WINDOW_CLOSED` and `ERR_CHALLENGE_LIMIT_REACHED` had no covering instance (found by the error-coverage sweep). Added a §1.9 instance walking both challenge cycles, the SoD refusal, the limit at day 0, and the window refusal at day 25.
18. YAML: `captures: { fa_id: $.data[0].id }` broke `safe_load` (nested `[` in a flow mapping) — quoted both occurrences.
19. A fee assert was written from memory as 4529; re-executed the formula in Python → **4471** (STATE_ONLY, processing 115). Corrected. All formula-derived asserts (5868, 5869, 42467, 41193, 1035, 891, 1067, 7668, 6368, 55000, 56035, 15400, 2200, 1523, 68.00, 62.00, 2026-04-30, 2026-06-02T10:00:00.000Z, 2028-02-29, 2026-12-07, 2026-11-11) were computed by code, not estimated.

Also closed two recurring cross-task bugs preventively: an explicit `datetime_rendering` block (three-fractional-digit UTC on output regardless of input format, all instants from the logical clock, date-only fields never widened) and an **exhaustive closed iff-list** for `ERR_INVALID_ENUM` in rung 6 ("no other field routes here").

**Orchestrator independent verification:** `yaml.safe_load` on all three files → clean; `SCAFFOLD.yaml` top-level counts re-parsed → entities 17, state_machines 17, calculations 21, validations 40, endpoints 73, errors 38, concurrency_rules 3, domain_constants 40 (all match the summary); independent ALL_CAPS token sweep → 41 residual tokens, all HTTP verbs / prose words / action-verb enum members / acronyms / one sample ORI literal, **0 undeclared constants** — confirms the agent's sweep.

## Step 4: Generate PRD — 2026-08-08T14:10:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_0929_livescan_fingerprinting/workspace/PRD.md`. Neither withheld design file was opened.

## Size and structure

**601 lines, 18,358 words, 132,755 bytes.** Written in 7 bounded Write/Edit calls; the file persisted after each.

- **§1 Introduction** — 3 paragraphs (ORI as parameterizing spine; three-axis submission; billing gate + retroactive calibration).
- **§2 Global Specifications** — 12 subsections: 2.1 Actors/RBAC · 2.2 API Response Structure (verified byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination, Filtering and List Ordering · 2.4 Resource Identity, Timestamps and the Datetime Contract · **2.5 The Version-Bump Ledger** · 2.6 The Logical Clock · 2.7 OCC · 2.8 Money, Percentages and Rounding · 2.9 The Ordered Validation Ladder · 2.10 The Agency Billing Freeze and Its Exclusion List · 2.11 Conservation Invariants · 2.12 Nested Paths and Left-to-Right Resolution.
- **§3 Business Logic** — 9 subsections: 3.1 Agencies/ORIs/authority profile · 3.2 Sites, scanners, roster · 3.3 Applicants, booking, counter · 3.4 Capture · 3.5 Transmission/TCN/destination results · 3.6 Dissemination/determination/challenge · 3.7 Retention/purge/rap-back · 3.8 Rejections/reprints/calibration sweep · 3.9 Fees/invoicing/aging/delinquency.
- **§4** 73-row table (Method, Path, Description, Authorized Role(s)) · **§5** 38-row table (Error ID, HTTP Status). File ends at §5 — no audit footer.

## Verified coverage counts (mechanical diff against scaffold, strict whole-backtick-token match)

| Category | Required | Present | Missing |
|---|---|---|---|
| `entities[].fields[].name` | 155 | 155 | 0 |
| endpoint request-body identifiers | 74 | 74 | 0 |
| endpoint query params | 29 | 29 | 0 |
| path params (`id`, `position_code`) | 2 | 2 | 0 |
| error IDs | 38 | 38 | 0 |
| role names | 6 | 6 | 0 |
| distinct state values (17 axes, 83 transitions) | 58 | 58 | 0 |
| enum member values | 119 | 119 | 0 |

Endpoints: 73/73 in §4 and each reachable from §3 narrative. Ladder rungs: 40/40 rendered individually with position, condition, error ID, HTTP status, and explicit scope list. Calculations: 21/21 (all 6 dual-variant rules render both the pinned and the rejected reading with its divergent number; all 4 conservation invariants in §2.11). State-machine axes: 17/17. Declared constants: 40/40 — 37 appear as literal numerals, 3 (`PROCESSING_SURCHARGE_PCT`, `VENDOR_TAX_PCT`, `INVOICE_LATE_FEE_PCT`) are rendered as exact words ("three and a half percent", "seven and a quarter percent", "one and a half percent") per the unit-conversion guidance. §3 path purity: 1,125 backtick tokens scanned, 0 path-leading, 0 bare-method, 0 method+path.

## Version-bump ledger

**§2.5**, lines 104–152. Pins `version` starting at 1; **once per request per row**, never once per cascade leg; reads never bump (including the three clock-driven lazy re-derivations — subscription `RENEWAL_DUE`/`LAPSED`, device `EXPIRED`, assignment `ACTIVE` — and `aging_days`). 32 per-operation entries. Named non-bumps include: cancel creates no assessment; `APPLICANT_PAID` transmission does not bump the agency; a root-preserving reprint does not bump the ORI; purging a suffix reprint does not bump the ORI; already-`ACKNOWLEDGED` notifications, already-`CANCELLED`/`LAPSED` subscriptions and already-`VACATED` determinations are untouched by the purge grant; acknowledgment does not bump the subscription (both statuses count the same); zero-shortfall reconciliation creates no assessment; unchanged invoices/agencies in a batch run; fixed-site appointments in the suspension cascade; clock-set bumps nothing.

## Un-adjudicated friction points carried forward (7)

1. **Fee-component conservation vs the two flat kinds** — §2.11. Reading A: the component equality is scoped to `SUBMISSION`/`REPRINT` only, so a `NO_SHOW` row legitimately reads `total_cents` 1500 against seven zero components. Reading B: the equality is universal, so those kinds must carry the charge inside a named component.
2. **Device recalibration ordering + missing state-error mapping** — §3.2. (a) The `QUARANTINED → CALIBRATED` leg declares `calibrated_at` must not precede `last_calibrated_at`; the `EXPIRED → CALIBRATED` leg does not restate it — applies to both legs, or only out of quarantine. (b) Rung 10 names no code for `Device`/`Ori`/`ServiceType`/`CaptureSite` state violations; both `ERR_RECORD_STATE_INVALID` (409) and `ERR_INVALID_REQUEST` (400) are rendered as supported readings.
3. **Dissemination projection scope** — §3.6. The per-role projection is declared for the single-response read only; the submission-scoped response listing accepts no `include_detail` and `StateRepository` is absent from the projection mapping. Reading A: same projection applies to the listing. Reading B: the listing returns stored rows unprojected.
4. **Where the `REPRINT` fee assessment is created** — §3.8. The fee rule's trigger names the reprint authorization; the authorization's own effect list creates only the replacement card, and the transmission is separately described as creating the `REPRINT` assessment that reads the stamped `free_reprint_granted`.
5. **`mtd_billed_cents` semantics** — §3.9. Running accumulator (never resets, never subtracts on credit) vs month-scoped sum over the current calendar month excluding `CREDITED` rows.
6. **`FEE_WAIVED` assessments settle nowhere** — §3.9. Invoice attachment names `AGENCY_BILLED` alone (so `FEE_WAIVED` rows stay `ASSESSED` for ever), while `invoice_id` is described as null only for `APPLICANT_PAID`, implying `FEE_WAIVED` rows were expected to attach.
7. **Agency return to `CURRENT`** — §3.9. Transition-precondition reading (no remaining `ISSUED`/`PAST_DUE` invoice with balance; `outstanding_balance_cents` and `max_aging_days` both forced to 0; `suspended_at` cleared) vs the delinquency-posture projection (largest `aging_days` of 0 makes it `CURRENT` regardless of unpaid balance; `outstanding_balance_cents` is the sum over remaining open invoices).

**One pointer defect resolved rather than carried:** the scaffold cross-references the billing freeze as `validations[priority=6]` in three places while defining it at priority 7 (priority 6 is enum membership, which has no write set). Since the literal reading is incoherent and rung 7 enumerates the frozen and excluded sets in full, the PRD renders the freeze at rung 7 with no behavioural ambiguity. The freeze is rendered in §2.10 as two closed enumerations — 13 frozen operations and the full exclusion list (every `GET` plus 22 named `POST` operations) — never as a universal over "all writes".

## Step 5: Generate unit tests — 2026-08-08T14:45:00.000Z

Test infrastructure and suite are complete.

## Exit summary

**Emitted: 101 tests** across 10 files in `test_suite/`, backed by 9 modules in `test_helpers/`.
- **Queue A (Difficulty): 38 tests** — all 18 instances covered, every one with ≥2 tests.
- **Queue B (Corner): 63 tests** — all 40 live instances covered with ≥1 test; the 10 `excluded_because` stubs produced no tests (all 10 `difficulty_instance` pointers were verified to resolve).

**Instances skipped: none.** Every non-stub instance survived the PRD-first two-condition filter.

**Assertions dropped inside an otherwise-translated instance (1):** `Corner/state_machines/exception_override_needs_a_third_exception_and_a_different_actor` asserts that an override attempted while only *one* position is exception-coded returns `ERR_CARD_STATE_INVALID`. PRD §3.4 states the precondition ("grants the override on a card that is `CAPTURING` and whose `positions_exception_count` already exceeds 2") but never names an error for being *under* the bound, and the card is genuinely in `CAPTURING`, so a faithful PRD-only reader could accept the early override. That probe was removed; the instance's core claims (SoD refusal, acceptance by a different supervisor, `exception_override_by_user_id` = `sup-77`) are asserted across two tests.

**Input deviations applied: 1.** `Corner/calculations/free_reprint_inside_tcn_window_extends_the_root_and_keeps_the_election` — the recipe locates the `REPRINT` assessment by `submission_id=<reprint submission>`. Substituted the lookup key to `appointment_id + assessment_kind=REPRINT`. Under friction point 4 the row is created either at authorization (no reprint submission exists yet) or at transmission; both readings set `appointment_id` and `assessment_kind`, and both produce the same components (0/0/0 statutory, total 1067). The instance's claim is asserted unchanged.

**Assertions relaxed to `validate_error_is_one_of`: none** — no surviving instance depended on a friction point that left two error codes open.

**The seven friction points, one by one:**
1. *Fee-component conservation vs the two flat kinds* — sidestepped. `assert_component_conservation` is explicitly scoped to `SUBMISSION`/`REPRINT` rows only; `NO_SHOW` (1500) and `ONSITE_SHORTFALL` (55000 / 2200) rows are asserted on `total_cents` alone, never on their seven components.
2. *Recalibration ordering + missing device state error* — sidestepped. Both recalibration tests supply a `calibrated_at` later than `last_calibrated_at`, so they pass under both readings; no test asserts an error code for a `Device`/`Ori`/`ServiceType`/`CaptureSite` state violation.
3. *Dissemination projection scope on the listing* — sidestepped. The listing is used only for `total_count` and row `id`; every field-level projection assertion goes through the single-response read, and `routing_status` is always read as `VendorAdmin` (the one role for which the PRD explicitly lists it). `routed_recipient_roles` is never asserted.
4. *Where the `REPRINT` assessment is created* — sidestepped by the input deviation above; no test observes the assessment before the replacement card is transmitted.
5. *`mtd_billed_cents` semantics* — sidestepped. Both `mtd_billed_cents` assertions (56035 and 42467) sit entirely inside June 2026 with no credited rows, where accumulator and month-scoped-sum agree exactly.
6. *`FEE_WAIVED` assessments settle nowhere* — avoided. No test invoices, pays or asserts the terminal status of a `FEE_WAIVED` assessment.
7. *Agency return to `CURRENT`* — avoided. The delinquency tests only drive `CURRENT → PAST_DUE → SUSPENDED`; no test pays an invoice to lift a posture.

**Guards:** all instant comparisons go through `parse_instant`/`assert_same_instant` in `test_helpers/assertions.py` (never raw-string equality); date-only fields (`due_on`) compare as strings via `assert_date_string`. Every queue-A instance's asserted operation was checked against the verb in its own `grounds` — no verb-scoping mismatch found.

**Verification performed:**
- 101 `def test_` functions; 101 `Design:` tags; exactly one per test; every tag resolves to a real non-stub instance (no stub tags, no dual tags).
- 171 PRD quotations of ≥8 words machine-checked against a whitespace-normalized `workspace/PRD.md` — 0 non-verbatim. Every test carries at least one citation.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere.
- No file in `test_suite/` or `test_helpers/` references the implementation (grep for `implementation`, `workspace/`, `start.sh`, `flask`, `import app` → none), and no comment or docstring mentions the scaffold.
- All modules import cleanly; pyflakes reports no undefined names and no unused imports; all fixture call sites bind against their real signatures, and all 13 composite setup chains were exercised against a stubbed client to confirm kwarg pass-through.

Key files: `test_helpers/fixtures.py` (composite setup, 5 tiers), `test_helpers/assertions.py` (instant helpers + conservation checkers), `test_suite/` (10 test modules).

## Step 6: Generate implementation — 2026-08-08T14:50:00.000Z

Implementation complete and verified.

## Modules (34 files, 4,150 lines total; Python 4,140)

**Foundation** — `app.py` 80 · `store.py` 91 · `constants.py` 114 · `errors.py` 54 · `timeutil.py` 125 · `money.py` 23 · `envelope.py` 97 · `authz.py` 159 · `validation.py` 194 · `lookups.py` 172 · `derive.py` 138 · `serializers.py` 394
**Services** — `fees.py` 114 · `billing.py` 85 · `cardsvc.py` 75 · `subsvc.py` 130 · `cascades.py` 252
**Routes** — `agencies` 44 · `oris` 81 · `service_types` 71 · `sites` 115 · `devices` 98 · `assignments` 97 · `applicants` 85 · `appointments` 207 · `cards` 219 · `submissions` 209 · `chr` 33 · `determinations` 122 · `rapback` 177 · `fees` 52 · `invoices` 132 · `ops` 101
**Launcher** — `start.sh` 9 · `requirements.txt` 1

## Completeness gate

**declared 73 / registered 73 / MISSING 0 / EXTRA 0.** Parsed `endpoints[]` from SCAFFOLD.yaml, booted in-process, dumped `app.url_map`, normalised `{id}`↔`<id>`, diffed both directions. Separately verified the 73-entry role map covers exactly the 73 registered rules (no endpoint silently skips rung 2). `grep -o 'exec python3 \S*' start.sh` → `exec python3 app.py`, file exists; `bash start.sh` boots and serves. Fresh boot has every collection empty (asserted over HTTP); storage is plain dicts, no disk.

## Bug 1 — timestamp rendering: closed

Single rule: **every** instant leaves through `timeutil.render_instant` — `%Y-%m-%dT%H:%M:%S` + milliseconds truncated to exactly 3 digits + `Z`. Caller input is parsed to an aware UTC datetime and re-rendered canonically, never echoed. Every instant comes from `db.now()` (the logical clock, default `2026-05-01T00:00:00Z`); `grep` confirms zero uses of `datetime.now/utcnow/time.time/date.today` anywhere. `api_request_timestamp` also reads the logical clock. Date-only fields are `datetime.date` objects rendered by `render_date` and are never widened. Verified over HTTP: input `2026-06-02T10:00:00.123456Z` → `2026-06-02T10:00:00.123Z`; `...12:00:00.5Z` → `...12:00:00.500Z`; bare `Z` → `.000Z`; `date_of_birth` stays `1990-01-02`.

## Bug 2 — enum routing: closed

`validation.ENUM_ROUTED_FIELDS` is the literal rung-6 list: **19 fields** — `payer_regime_default, statutory_authority, applicant_type, required_document_codes, accepted_id_document_types, site_kind, booking_channel, presented_document_type, sex, id_document_type, exception_code, destination, result_code, outcome, amended_outcome, resolution, decision, event_type, to_status`. `enum_value()` asserts membership in that frozenset, so an off-list field cannot reach `ERR_INVALID_ENUM`; everything else (missing field, wrong type, out-of-range, `ori_code` length, `slot_duration_minutes`, uniqueness, empty arrays) is `ERR_INVALID_REQUEST` at rung 5. Rung 5 runs entirely before rung 6.

## The seven friction points — my choices

1. **Fee-component conservation** → **scoped to SUBMISSION/REPRINT**. `NO_SHOW` reads `total_cents` 1500 against seven zero components. The universal reading would require inventing which named component carries the charge, contradicting §3.9's "0 for any other kind" per-component rules and making those declared zero values unreachable.
2. **(a) Recalibration ordering** → enforced **only on `QUARANTINED → CALIBRATED`** (PRD says that leg "additionally declares" it; the EXPIRED leg does not restate it), returning `ERR_INVALID_REQUEST` by symmetry with the audit's explicitly-pinned backwards-only code. **(b) Device/Ori/ServiceType/CaptureSite state violations** → **`ERR_RECORD_STATE_INVALID` 409**. Rung 5's enumeration is closed and contains no state comparison, so routing them to rung 5 would break rung 5's own declared scope; rung 10 is the state rung.
3. **Dissemination projection scope** → the submission-scoped listing returns **stored rows unprojected**. `StateRepository` is authorised for that listing but appears nowhere in the projection mapping, so applying the projection there is underivable; unprojected keeps all three roles well-defined and leaves the guarded single-read projection fully reachable.
4. **REPRINT assessment** → created at the **replacement card's transmission**. At authorization the new submission does not exist, so `federal_fee_cents` ("submission has FBI among its destinations") and the non-null `submission_id` are both underivable; §2.5's authorization ledger lists no assessment while the transmission ledger says "one new submission … and one new fee assessment".
5. **`mtd_billed_cents`** → **running accumulator**, never reset, never reduced by a credit. §2.5 lists exactly four fields re-derived on read and this is not one of them, and the ledger's "the agency bumps only if `mtd_billed_cents` actually changes" only makes sense for a stored accumulator.
6. **`FEE_WAIVED` assessments** → **stay `ASSESSED` for ever**; only `AGENCY_BILLED` rows attach. Both the PRD attachment sentence and the state-machine precondition name `AGENCY_BILLED`, and attaching a non-zero `FEE_WAIVED` total would falsify every declared invoice arithmetic.
7. **Agency return to `CURRENT`** → the **posture projection** governs uniformly (max_aging ≥45 SUSPENDED, ≥1 PAST_DUE, else CURRENT; outstanding = Σ balance over ISSUED/PAST_DUE), on the batch, on payment and on issuance alike. The alternative would set `outstanding_balance_cents` to 0 while an open unpaid invoice remains, contradicting the field's own declared definition. `suspended_at` is a historical stamp, set on each entry into SUSPENDED and never cleared — matching §3.1's wording.

## Further under-determined points and my calls

- **Applicant ownership checks (§2.1)** — declared, but no rung of the closed 40 and no error in the closed 38 covers a violation. **Not enforced**; enforcing it would invent an undeclared rung and would 403 legitimate flows whose `X-User-ID` is an operator badge.
- **Exception-override precondition `positions_exception_count > 2`** — no error code declared. Only `status == CAPTURING` is enforced at rung 10, keeping rung 11 (SoD) reachable.
- **No-show grace precondition** (clock > start+10 min) has no rung; treated as a rung-10 appointment-state precondition → `ERR_APPOINTMENT_STATE_INVALID` 409.
- **Retention check on renew** — rung 31's declared scope is `POST /rapback-subscriptions` only, so it is not applied to renew (a `PURGED` submission already terminates the subscription, caught by rung 10).
- **Uniqueness violations** (`account_code`, `ori_code`, `serial_number`, service-type `code` within ORI, invoice `period_key`) → `ERR_INVALID_REQUEST` 400 at rung 5, ahead of rungs 6 and 9.
- **Calibration audit admissibility** — allowed from `CALIBRATED` or `EXPIRED`, refused from `QUARANTINED` (409).
- **`invoices_aged`** counts invoices the run actually changed, matching §2.5's "an invoice whose recomputed `aging_days` is unchanged and which accrues nothing does not bump".
- **Card `SUBMITTED → CLOSED`** on the final destination result bumps the card, and the purge/audit site recomputation bumps the site, even though §2.5's per-operation entries omit them — §2.5's *governing* rule ("any request that changes at least one persisted field value") wins over the silent ledger entry.
- **201 vs 200** — followed the scaffold's explicit `code` for the two arguable cases (`attempts` and `destination-results` are 201); every other endpoint matches §4's rule exactly.
- **Requests are serialized** by a WSGI-level lock so multi-row cascades are atomic under concurrent load; bump bookkeeping is request-scoped via `flask.g`.

Validated over HTTP with five smoke suites (~230 assertions, all passing) covering every PRD worked example: fee totals 5868 / 5692 / 1035 / 1067 / 7668, per-component rounding 162 + 72 = 234, discount 176 / 32, late fee 85-style accrual, shortfall 7×2200, mean 68.00 over a divisor of 8 and the not-submittable ten-at-62 card, TCN `CA0111111-000001` → `-1` → `-2` → fresh `-000002`, the 30-day free-reprint and 90-day preservation boundaries, the leap-year term `2027-03-01 → 2028-02-29` with the window opening `2027-12-31`, walk-in reserve 5→4 / 10→8 / 1→0, the 29-vs-30-minute roster buffer, the six-hop purge and six-hop calibration cascades, the freeze and its exclusion list, and the full §2.5 version-bump ledger including every named non-bump.

**Orchestrator independent verification after Steps 5+6:** containment grep both directions — impl referencing `test_suite|test_helpers|conftest|pytest` → 0 hits; tests referencing `implementation|workspace/|start.sh|import app|flask` → 0 hits. Persistence grep over impl for `sqlite|json.dump|pickle|/tmp|datetime.now|utcnow|time.time()|date.today` → 0 hits. `def test_` 101 == `Design:` tags 101; `pytest.mark` occurrences 0. Independent route diff (scaffold `endpoints[]` vs in-process `app.url_map`, path params normalized) → declared 73 / registered 73 / MISSING 0 / EXTRA 0.

**Isolation overlap note:** Steps 5 and 6 were launched concurrently in one message, but Step 5 returned ~287 s *before* Step 6, so `test_suite/`+`test_helpers/` were on disk during impl-gen's final stretch. Containment greps above are clean; Step 7 is briefed to audit the suite for leakage signatures.

## Step 7: Run tests and iterate — 2026-08-08T15:09:00.000Z

All 8 rounds pass 101/101 with zero failures, errors, or skips. Done.

## Summary

**Iterations run:** 2 sweeps (baseline → 1 fix → clean).

**Tests deleted:** none. The single failing test passed both STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability), and STEP 2 found the test artifact faithful, so the fix landed in `implementation/`.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`:**
- `workspace/implementation/derive.py` → `assignment_status()` — a roster entry's derived status reverted from `ACTIVE` back to `SCHEDULED` once the logical clock passed `window_end` (the predicate was `window_start <= now < window_end`, falling through to the stored `SCHEDULED`). Changed to the monotone form: once `now >= window_start`, the entry reads `ACTIVE` until it is released or revoked.

**The failure and why the implementation was at fault.** `test_the_audit_moves_the_print_from_billable_to_tainted` failed identically in all 8 rounds on `assert assignment["tainted_print_count"] == 1` (got 0). The lapse audit revoked the roster entry whose window had already elapsed; because the entry read `SCHEDULED` at that instant, hop 6 applied the PRD's carve-out ("A roster entry revoked from `SCHEDULED` keeps a `tainted_print_count` of 0") and dropped the capture. Three PRD sentences make the impl's reading untenable:
- §2.11 Billable print conservation: "the site's `billable_print_count` plus the sum of `tainted_print_count` over every device assignment at that site equals the number of fingerprint cards at that site whose `status` is `SUBMITTED`, `CLOSED` or `REJECTED_CLOSED`, together with those whose `status` is `SUPERSEDED` with a `taint_reason` of `CALIBRATION_LAPSE`… A lapse audit therefore moves each tainted card from the billable side of the ledger to the tainted side, leaving the sum unchanged. Checked after every transmission, every calibration audit and every event reconciliation." Under the old behaviour the post-audit ledger read 0 + 0 = 0 against a right-hand side of 1 — a stated invariant violated inside the very request that disturbs it.
- §3.2 names only `SCHEDULED → ACTIVE`; the only exits from `ACTIVE` are `RELEASED` and `REVOKED_TAINTED`, "both terminal". No sentence returns an entry to `SCHEDULED`.
- The carve-out's own stated rationale — "because a scheduled window has no captures behind it yet" — is false for an elapsed window, which confirms `SCHEDULED` was never meant to describe one. (The same reasoning applies to §3.2's "Releasing from `ACTIVE` recomputes the entry's `billable_print_count`", which the old derivation would also have skipped for an elapsed window.)

The change is contained: capture gating in `routes/cards.py::_check_device_ready` already re-checks window containment explicitly, and the roster-conflict rule and event reconciliation both treat `SCHEDULED` and `ACTIVE` alike, so no other behaviour moved.

**None of the seven friction points was implicated** — this was a genuine implementation bug against a hard invariant, not an under-determined reading.

**Isolation-overlap leakage audit — clean on all four checks:**
1. *Instant comparisons* — `test_helpers/assertions.py` defines `parse_instant`/`same_instant`/`assert_same_instant`; a grep for raw string equality against any `*_at`/`*_on`/`timestamp`/`instant` field across `test_suite/` returned zero hits.
2. *Order/position assertions* — the only index-0 assertions are `test_02:268-269`, `test_06:81` and `test_07:115`, and each is immediately preceded by `assert meta["total_count"] == 1`, so no declared sort or tie-break is relied on. `test_04:55` compares `sorted(...) == sorted(POSITION_CODES)`, order-independent.
3. *Exact `version` assertions* — 7 total, all at 1/2/3 for create-plus-N-mutations or `version + 1`, each traceable to the §2.5 ledger lines for agency/ORI creation, ORI suspend-reinstate, and applicant correction.
4. *Response-field names* — all 150 distinct subscript keys in `test_suite/` and all 91 in `test_helpers/assertions.py` were checked against `workspace/PRD.md`; the only 18 non-matches are local `world`/fixture dict keys (`event_site`, `card_a`, `billable_before`, `*_headers`, …), not response fields.

Containment greps in both directions were also re-run and returned empty: no implementation file references `test_suite`/`test_helpers`/`conftest`/`pytest`, and no test file references any implementation module.

**Final per-round results** (`workspace/implementation/results.{1..8}.json`, all preserved): rounds 1–8 all 101/101.

**Orchestrator independent verification:** all 8 `results.N.json` re-parsed — **101 individual rows each** (not just an aggregate counter), `passed=101 failed=0 errors=0 skipped=0` every round, sorted test-name lists byte-identical to round 1 in all 8; `pytest.mark` occurrences 0; `find implementation/ test_suite/ test_helpers/ -name '*.py' -newer results.1.json` → empty, so the green result describes the shipped tree. Sweep ran as 2 waves of 4 via the pre-staged `workspace/sweep.sh`; ~72 s/wave, ~2.5 min/sweep; zero boot-timeout ERRORs, zero SIGTERM.

**Step 8 does NOT skip:** the skip condition requires all four counts at zero; `implementation/` fixes = 1.

## Step 8: Finalize PRD — 2026-08-08T15:15:00.000Z

`PRD_FINALIZED.md` is written. Three edits, all traced to the single Step 7 fix (`derive.py::assignment_status` going monotone).

## Line counts / delta
- `PRD.md`: 601 lines / 132,755 bytes
- `PRD_FINALIZED.md`: 601 lines / 133,749 bytes
- **0 % line delta** (no lines added or removed; three lines revised in place), **+0.75 % bytes**

## Changes
- **§3.2 (line 288) — revise — the derived roster-entry status.** Dropped `and strictly before window_end` from the `SCHEDULED → ACTIVE` condition; stated that the move is one-way, that an entry carried past `window_end` without a release or revocation goes on reading `ACTIVE`, that nothing returns an entry to `SCHEDULED`, and therefore that rung 20's separate window-containment test is what stops captures and that a lapse audit revokes an elapsed entry **from `ACTIVE`**. — `implementation/derive.py:27-41`
- **§3.2 (line 290) — insert — event reconciliation's bulk release.** Added one sentence: the reconciliation's bulk release only moves `status` and leaves each entry's `billable_print_count` as it stands, whichever status the entry was reading. — `implementation/routes/sites.py:107-113`
- **§4 endpoint table (line 505) — revise — release blurb.** "before or during its window" → "before, during or after its window". — `implementation/routes/assignments.py:87-97`

## Per-edit pre-edit search log

**Edit 1 — subject: derived lifecycle status of a device assignment.**
(b) Enumerated and read every impl path consuming `assignment_status`: `derive.py:27` (the derivation itself), `serializers.py:119` (the `status` field on every read; no write), `routes/assignments.py:40` (roster-conflict rule), `routes/assignments.py:83` (list `status` filter), `routes/assignments.py:90-94` (release), `routes/cards.py:31-40` `_check_device_ready` (rung 20 — status check **plus** an explicit `window_start <= now < window_end`), `routes/sites.py:107-113` (reconciliation bulk release), `cascades.py:105-112` (audit hop 2, records `_revoked_from`) and `cascades.py:182-191` (hop 6 carve-out, keyed on `_revoked_from == "ACTIVE"`). Also `grep '"SCHEDULED"'` across the tree to confirm the only write of `SCHEDULED` is at creation (`routes/assignments.py:58`) — nothing returns an entry to it. Cross-checked the PRD sentences that mention the two statuses and left them verbatim after confirming each still holds: §2.5 line 110, §3.2 line 286, rung 20 line 202, §3.7 line 318, §3.8 lines 428/432 (the `tainted_print_count` carve-out's rationale becomes exactly true), §2.11 line 244 (invariant now balances).
(c) Two adjustments made before committing. First, the original clause "that is what makes captures … permitted" would have become false standing alone (an entry reads `ACTIVE` past `window_end` but admits no capture), so the window-containment condition was re-attached to the *capture* clause rather than deleted. Second, an earlier draft said "a release **or** a lapse audit treats an elapsed entry as `ACTIVE`" — that would have implied the reconciliation's bulk release recomputes `billable_print_count`, which `routes/sites.py` does not do; the clause was narrowed to the lapse audit only, and the reconciliation case handled separately in Edit 2.

**Edit 2 — subject: whether a release recomputes `billable_print_count`, for each of the two release paths.**
(b) Read `routes/assignments.py:87-97` (endpoint release: `ACTIVE` leg calls `cardsvc.billable_count_for_assignment`, `SCHEDULED` leg does not), `routes/sites.py:107-113` (reconciliation: sets `status` and `db.touch` only — no counter write on any branch), `cardsvc.py:65-73`, and the version-ledger bullets §2.5 lines 118 and 145 to confirm the bump counts still match.
(c) Wording scoped the recomputation to "the `SiteSupervisor`'s release endpoint alone" and made the non-recomputation explicit for *both* possible readings ("whichever of the two statuses the entry was reading").

**Edit 3 — subject: the release endpoint's admissibility window.**
(b) Read `routes/assignments.py:87-91` (`require_record_state(current in ("SCHEDULED","ACTIVE"))` — no window test at all), `lookups.py` usage via `require_record_state`, and PRD §2.10 line 232 (release is on the billing-freeze exclusion list).
(c) None — kept the table's original phrasing shape and only widened "before or during" to "before, during or after".

Note carried to Step 9: `GET /livescan/device-assignments` also accepts an undocumented `status` filter (`routes/assignments.py:83`, compared against the *derived* status) — a pre-existing PRD silence unrelated to the Step 7 fix.

## Step 9: Complete PRD — 2026-08-08T15:35:00.000Z

`PRD_COMPLETED.md` is complete. Summary below.

## Deltas

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| Lines | 601 | 608 (+7: 3 new paragraphs inside existing sections, 1 new §2.5 bullet) |
| Chars | 133,749 | 158,423 (**+24,674**) |
| Modified source lines | — | 53 |

Heading structure verified byte-identical (`diff` of all `^#` lines is empty). Tables (115 rows), code fences (4), and numbered lists (57) all unchanged in count.

**Counts:** 24 ambiguity-pins, 19 mismatch-revisions (43 edits total).

## The seven friction points — all converted, with code evidence

1. **Fee-component conservation (§2.11)** → scoped to `SUBMISSION`/`REPRINT`. `fees.py:28-49` `_blank()` sets all seven components to 0; `fees.py:101-106` `create_no_show_assessment` stamps `total_cents = 1500` on top of that blank; `fees.py:109-114` does the same with the shortfall.
2. **(a) Recalibration ordering (§3.2)** → `devices.py:73` — `if current == "QUARANTINED" and calibrated_at < device["last_calibrated_at"]` → `V.bad_request` (`ERR_INVALID_REQUEST` 400). The `EXPIRED` leg is unguarded. **(b)** Device/ORI/ServiceType/CaptureSite → `ERR_RECORD_STATE_INVALID` 409: `devices.py:68,90`, `oris.py:76-77`, `appointments.py:58`, `sites.py:89-94`, all via `lookups.py:136-138`.
3. **Dissemination projection scope (§3.6)** → `submissions.py:139` returns `paginate(rows, serializers.chr_response)` — the raw serializer; `serializers.py:363` `project_chr_response` is called only from `chr.py:33`.
4. **`REPRINT` creation point (§3.8)** → `cascades.py:218-252` `authorize_reprint` creates no assessment; `submissions.py:62-65` builds `kind = "REPRINT"` at transmission and reads `card["free_reprint_granted"]` at `fees.py:65`.
5. **`mtd_billed_cents` (§3.9)** → `fees.py:52-56` `+=` only; grep confirms it is written nowhere else (no reset in `ops.py`, no subtraction in `cascades.py` hop 5 or the write-off branch).
6. **`FEE_WAIVED` assessments (§3.9)** → `invoices.py:78-84` attaches only `payer_regime == "AGENCY_BILLED"`; `fees.py:42` (rung 39) blocks the counter path.
7. **Agency return to `CURRENT` (§3.9)** → `billing.py:24-58` `recompute_agency_posture` is the single 45/1/0 projection over `ISSUED`/`PAST_DUE` invoices, called from `ops.py:61`, `invoices.py:101,131` and `cascades.py:174`; `suspended_at` is written at `billing.py:50` and cleared nowhere.

## Change log

**§2.1** — revise — mismatch — no ownership check exists anywhere; `X-User-ID` is never compared to a row `id` or applicant FK, and lists are not narrowed by caller — verified by grep: `g.user_id` appears only in `lookups.py:144` (segregation) and actor-stamping sites.
**§2.3** — insert — ambiguity — UUID tie-break means a card's ten positions return in `id` order, not anatomical order — `envelope.py:86-89`.
**§2.3** — insert — ambiguity — complete per-endpoint query-parameter roster (16 listings), the four derived-value filters, and off-enum values yielding an empty page not a 400 — `oris.py:57-62`, `service_types.py:65-70`, `sites.py:77-82`, `devices.py:52-57`, `assignments.py:75-83`, `appointments.py:91-94`, `cards.py:84-104`, `submissions.py:77-83,133-135`, `determinations.py:68-71`, `rapback.py:64-70,161-164`, `fees.py:21-31`, `invoices.py:63-66`.
**§2.5** — revise — mismatch — applicant correction bumps only on an actual value change — `applicants.py:83-84`.
**§2.5** — insert — ambiguity — audit hop 5 also bumps invoices and the owning agency — `cascades.py:164-174`.
**§2.5** — revise — mismatch — transmission bumps the appointment only when still `IN_CAPTURE`; a replacement card's transmission does not — `submissions.py:57-59`.
**§2.5** — insert — ambiguity — destination result bumps the card on the `SUBMITTED → CLOSED` leg (ledger omission #1) — `subsvc.py:121-130`.
**§2.5** — insert — ambiguity — purge grant bumps the capture site when its recomputed count changes (ledger omission #2) — `cascades.py:89-91` + `cardsvc.py:59-65`.
**§2.5** — insert — ambiguity — new bullet: the suspension cascade also runs on issuance, payment and audit, not only the batch — `billing.py:56-57`.
**§2.5** — insert — ambiguity — batch also bumps written-off invoices and their `INVOICED` assessments; exact semantics of all four returned counters — `ops.py:20-92`.
**§2.8** — insert — ambiguity — `mean_quality_score` is a bare JSON number, so 68.00 renders as `68.0` — `serializers.py:180`.
**§2.9 r4** — revise — mismatch — scope list omitted `POST /submissions/{id}/reprints`; rap-back `ori_code`/`subject_submission_tcn` are not FKs — `submissions.py:147`, `rapback.py:116-117`.
**§2.9 r5** — insert — ambiguity — uniqueness violations, non-enum closed sets, and both calibration-audit guards all route here as `ERR_INVALID_REQUEST` — `lookups.py:160-168`, `devices.py:92-95`.
**§2.9 r10** — revise — mismatch — the `ERR_RECORD_STATE_INVALID` set closed over 12 entity types (adds device, ORI, service type, capture site); `SUPERSEDED` card covers the reprint case — `submissions.py:155-156`.
**§2.11** — revise — **friction 1**.
**§2.12** — insert — ambiguity — new paragraph: unknown path → `ERR_REFERENCE_NOT_FOUND` 404, undeclared method → `ERR_INVALID_REQUEST` 400, neither reaching the role rung — `app.py:66-70`.
**§3.1** — insert — mismatch — `fee_waiver_eligible` is stored, returned and read by nothing — grep-confirmed.
**§3.1** — insert — ambiguity — ORI authority no-op transition → `ERR_RECORD_STATE_INVALID` — `oris.py:76-77`.
**§3.1** — revise — ambiguity — `RETIRED` service type booking refusal → `ERR_RECORD_STATE_INVALID`, positioned after the freeze — `appointments.py:58`.
**§3.2** — revise — **friction 2 (a) and (b)**.
**§3.2** — insert — ambiguity — rostering is frozen only via a mobile event's host agency; a `FIXED`-site roster is never frozen — `assignments.py:32` + `lookups.py:94-97`.
**§3.2** — insert — ambiguity — release refusal code, derived-status test, response body — `assignments.py:90-97`.
**§3.2** — insert — ambiguity — reconciliation's three guards are all `ERR_RECORD_STATE_INVALID`, ordered kind → window → status — `sites.py:89-94`.
**§3.3** — insert — ambiguity — only three fields are correctable, explicit `null` is a no-op, `demographics_complete` is consulted by nothing — `applicants.py:59-82`.
**§3.3** — insert — ambiguity — all three cancel refusals are `ERR_APPOINTMENT_STATE_INVALID`, including the applicant-on-`CHECKED_IN` case — `appointments.py:131-145`.
**§3.3** — insert — ambiguity — `presented_documents` may be empty and its members are not enum-checked — `appointments.py:157`.
**§3.3** — insert — ambiguity — no-show grace boundary is strict; refusal is `ERR_APPOINTMENT_STATE_INVALID` — `appointments.py:197-200`.
**§3.4** — revise — mismatch — exception-override does **not** require `positions_exception_count > 2` — `cards.py:182-195`.
**§3.4** — insert — ambiguity — `submittable` is consulted by nothing; both position writes return the position row; attempts answer 201, exception 200 — `cards.py:148,179`, `cards.py:204-215`.
**§3.4** — revise — mismatch — finalize evaluates rung 25 before rung 26, inverting the narrated order — `cards.py:205-215`.
**§3.5** — revise — ambiguity — site counter is recomputed, never incremented — `submissions.py:60` + `cardsvc.py:59-65`.
**§3.5** — insert — ambiguity — chain head resolved in one hop via `original_submission_id`; both questions read the head's fields — `subsvc.py:29-40`.
**§3.5** — insert — ambiguity — payload defaults, `rejection_reason` discarded, state check before destination check, body is the submission, 201 on all six legs — `submissions.py:93-126`.
**§3.6** — insert — ambiguity — a response created while the submission is `PURGED` stays `RECEIVED` with null `routed_at`/`routed_recipient_roles` — `subsvc.py:109-113`.
**§3.6** — revise — **friction 3**, plus `include_detail` parsing (`true`/`1`, case-insensitive) — `chr.py:12-16`.
**§3.6** — insert — ambiguity — `basis_response_id` may be null and issuance is not gated on `composite_disposition` — `determinations.py:32-39`.
**§3.6** — insert — ambiguity — `AMEND` leaves `challenge_filed_at`; `amended_outcome` is enum-checked then discarded under `REAFFIRM` — `determinations.py:102-119`.
**§3.7** — revise — ambiguity — purge hop 3 reaches *every* subscription of the submission and tests the derived status — `cascades.py:48-52`.
**§3.7** — revise — mismatch — renewal never re-reads the submission's `retention_status`, making `ERR_RAPBACK_REQUIRES_RETENTION` unreachable there — `rapback.py:74-98`.
**§3.7** — insert — ambiguity — notification binding takes the earliest-created match and tests the derived status — `rapback.py:122-133`.
**§3.8** — revise — **friction 4**.
**§3.8** — revise — ambiguity — audit's three gates, their order and codes; `QUARANTINED` device refused with `ERR_RECORD_STATE_INVALID` — `devices.py:89-95`.
**§3.8** — revise — ambiguity — reprint's `SUPERSEDED`-card guard runs first; retention does not gate; body is the card, 201 — `submissions.py:155-168`.
**§3.8** — insert — ambiguity — hops 2/4/5/6: legs that don't fire, what hop 4 does *not* cascade to, `mtd_billed_cents` untouched by credits, `tainted_card_count` set not accumulated, `taint_reason` read by nothing — `cascades.py:104-196`.
**§3.9** — revise — mismatch — three creating operations, not four; `ONSITE_SHORTFALL` forces `AGENCY_BILLED` — `fees.py:111`.
**§3.9** — revise — **friction 5**, **friction 6**, **friction 7**.
**§3.9** — insert — ambiguity — counter/invoice payment state gates, zero-rounding late fee, write-off only from `PAST_DUE`, `write_off_over_days` of 0 — `fees.py:41`, `invoices.py:111-113`, `ops.py:34,42-47`.
**§3.9** — revise — ambiguity — posture recomputed by exactly four operations; a `DRAFT` invoice moves neither figure — `billing.py` call sites.
**§4** — revise — mismatch — the 201 rule now carries its two named exceptions (attempts; destination-results) — `cards.py:148`, `submissions.py:126`.

**Orchestrator independent verification after Step 9:** `diff` of all `^#` heading lines, `PRD.md` vs `PRD_COMPLETED.md` → identical (no new sections); line counts 601 / 601 / 608; all 8 `results.N.json` still present; `find implementation/ test_suite/ test_helpers/ -name '*.py' -newer results.1.json` → **empty**, so the 8×101/101 green result still describes the shipped tree; impl persistence re-grep (`sqlite|json.dump|pickle|/tmp|datetime.now|utcnow|time.time()|date.today`) → 0 hits.

## PIPELINE COMPLETE — 2026-08-08T15:40:00.000Z

All 9 steps done. Final state: **101/101 tests passing on all 8 stability-sweep rounds**, 1 implementation fix, 0 test deletions, 0 test edits. Artifacts: `SCAFFOLD.yaml` + both design YAMLs, `workspace/PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md`, `test_helpers/` (9 modules), `test_suite/` (10 modules, 101 tests), `workspace/implementation/` (34 files, ~4,150 lines), `workspace/implementation/results.{1..8}.json`.
