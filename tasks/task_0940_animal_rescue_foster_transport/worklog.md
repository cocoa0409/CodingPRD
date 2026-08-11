# Worklog — task_0940_animal_rescue_foster_transport

Scenario (verbatim): `940. Animal Rescue & Foster/Transport Network: intake & transport (rescue leg), foster application & home-check, foster placement & medical, adoption application & match, transport-relay coordination, donation & sponsorship, return/RTO, live-release outcome`

Difficulty: **beyond-Expert** (user asked "generate task hard than expert level!").

## Step 1: Create task directory — 2026-08-09T04:36:00.000Z

Created `tasks/task_0940_animal_rescue_foster_transport/workspace`. Index note: `task_0938_*` and `task_0939_*` were being created concurrently by a co-tenant session on this host, so this task took index 0940 (which also matches the scenario's own number). Host: 8 cores, load 0.89 at start, co-tenant pipelines active — relevant to Step 7 sweep scheduling.

## Step 2: Generate scaffold — 2026-08-09T05:33:00.000Z

All three scaffold artifacts are generated and lint-clean at `/home/ubuntu/github/CodingPRD/tasks/task_0940_animal_rescue_foster_transport/`.

### Final counts

| Dimension | Value |
|---|---|
| Entities | **19** (Organization, Person, Animal, Litter, IntakeRecord, HoldRecord, FosterHome, FosterApplication, FosterPlacement, MedicalRecord, HealthCertificate, TransportRun, TransportLeg, ManifestEntry, AdoptionApplication, Adoption, OutcomeRecord, Contribution, PartnerCommitment) |
| Endpoints | **84** |
| Error codes | **48** |
| Ladder rungs | **45**, single global ordering, contiguous 1–45 |
| Status axes | **19 across 14 entities, 14 non-linear** (6 cyclic, 4 branching, 2 parallel, 1 cyclic-parallel, 1 capped-cycle; 5 linear incl. 1 declared-monotone) |
| Calculations | **37, 10 dual-variant** (variant selected by a declared enum/flag: `identifiable`, `impound_billing_basis`, `species` ×2, `credit_application_order`, `deposit_basis`, `refund_basis`, `methodology`, `count_basis`, `transport_basis`) |
| OCC rules | **3** (Animal on adoption-finalize, TransportLeg on manifest-add, FosterHome on placement-create) |
| Conservation invariants | **6** (episode counts, donated cents, foster slots, partner slots, crate units, fee components) |
| Cascades | **depth-6** (TransportLeg→ManifestEntry→Animal→TransportRun→PartnerCommitment→Organization) and **two depth-4** (Adoption→OutcomeRecord→Contribution→Organization; Adoption→OutcomeRecord→IntakeRecord→Animal) |
| Ordered write gates | **5** (records-freeze → outcome-closed → legal hold → medical hold → behavioral hold, asymmetric scopes) |
| Constants declared | **56** |
| §1.8 instances | 9 rules × 2 = **18** |
| §1.9 instances | **70** across 8 sections (59 with full recipes, 11 `excluded_because` stubs) |

### Audit results

**YAML lint** — `yaml.safe_load` OK on all three. Two known offenders hit and fixed: PyYAML terminates plain scalars at `?` in flow context (all `input: [x?, …]` optional markers quoted) and at `[` in flow context (all `$.data[0].field` captures and `grounds: [errors[…]]` entries quoted).

**Undeclared-constant sweep** — every ALL_CAPS underscore token across all three files cross-checked against `global_constants`, enum members, state names, error ids and role names. **56 declared, 0 undeclared** (only `ERR_XXX` from the verbatim §1.0 envelope remains, as required).

**Reachability self-repairs made (7)**
1. **`ERR_HOLD_ALREADY_EXPIRED` was dead** — rung 18 (generic state-machine check) pre-empted it on every path, since `HOLD_EXPIRED` is terminal. Repaired by scoping rung 18 to exclude `POST /animals/{id}/identification`, whose hold-axis precondition is now checked only at rung 21.
2. **`intake_outcome_conservation` did not hold across a return** (2 ≠ 0+1). Repaired by adding an `IntakeRecord CLOSED → VOIDED` transition fired by the outcome reversal, so the RETURN episode replaces the superseded one one-for-one.
3. **`AdoptionApplication.decline_reason = HOUSEHOLD_MISMATCH` was an unproducible enum value** — the mismatch rejects the create at rung 24, so no row can carry it. Removed from the enum.
4. **Mutate-then-reject removed from the CVI path** — `HealthCertificate VALID→EXPIRED` was declared as a side effect of a *rejected* departure, which also invalidated downstream legs. Reworked to a read-time derivation; `TransportLeg → INVALIDATED` is now produced only by run abort/cancel (still reachable).
5. **CVI destination matching was fuzzy** ("the destination organization's state_code" — undefined for non-transfer runs). Added `TransportLeg.destination_state_code` as an input field and pinned rungs 34/35 against it, plus a governing-certificate selector (greatest `issued_at`, tie-break greatest `created_at`) so a renewed certificate does not fail on an older expired sibling.
6. **Rungs 10/11 carried a fuzzy error mapping** ("the error_id is the one declared for the missing entity"). Replaced with a closed entity→error map; added a corner instance so all 7 previously-unreferenced not-found codes are exercised. **All 48 error codes are now triggered by at least one design instance.**
7. **`POST /foster-placements/{id}/end` accepted system-only reasons.** Restricted the client-supplied `reason` to `RETURNED_TO_SHELTER` / `CANCELLED_BEFORE_START`.

Arithmetic-feasibility checks passed: the 20000¢ hardship-waiver threshold is straddled on both sides (16500 vs 27000); the AGE_SCALED deposit clamps bind at both ends (12 wk → floor 6000, 0 wk → cap 18000); the foster home can be slot-open and head-full simultaneously; leg crate and weight capacities fail independently.

**Worked examples** — every `test_recipe` numeric was executed in Python before being written (fee waterfall 20000/3000/2000 vs 10000/15000/0; live-release 0.25 SAC vs 0.5 ASILOMAR; impound 6 d/12000/16500 vs 5 d/9500/14000; hardship 22500→27000→25000; repeat-multiplier 7000→10500→15000; per-line overhead 801 vs 800-if-summed-first; deposits 15000/9600/6000/18000; refund 1000 + 10000 restored; all date arithmetic incl. 2026-10-29, 2027-04-28, 2026-06-04).

**Extra self-checks run** — 87 instance names unique across both design files; 0 unresolved `grounds` references; 0 unbound `${var}` placeholders across 899 calls; all 11 `excluded_because` stubs cite a §1.8 instance that exists.

**`scaffold_lint.py` verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    84
  §1.1 entities declared:     19
  §1.8 instances scanned:     18
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  899

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Nothing was written outside the three output files, and no sibling task directory was read.

**Orchestrator independent verification:** all three files `yaml.safe_load` clean (4232 / 1678 / 3521 lines); `global_constants` has 56 entries; independent ALL_CAPS-underscore sweep found 160 tokens, 28 residual after subtracting constants/enums/states/errors/roles — all 28 manually confirmed to be enum members (`AGE_SCALED`, `WAIVER_FIRST`, `EUTHANASIA_OWNER_REQUESTED`, …) plus the `ERR_XXX` envelope placeholder; **zero** carry a value-bearing suffix (`_DAYS`/`_LIMIT`/`_THRESHOLD`/`_MULTIPLIER`/`_RATE`/`_WINDOW`), confirming 0 undeclared constants.

## Step 3: Copy shared files — 2026-08-09T05:35:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0940_animal_rescue_foster_transport/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-09T05:52:00.000Z

The PRD is complete and all three hard contracts pass.

**Output:** `workspace/PRD.md` — **608 lines, 17,634 words**. Written in 7 bounded Write/Edit calls; ends correctly at §5's final error row (`ERR_RETURN_WINDOW_CLOSED | 409`).

**Structure:** §1 intro (3 paras) · §2 with 11 subsections (2.2 verified byte-identical to `section-2.2-response-structure.md`) · §3 with 9 domain subsections · §4 4-column table · §5 2-column table.

### Coverage counts

| Scaffold element | Required | Covered | Gap |
|---|---|---|---|
| Endpoints | 84 | 84 (§4 table rows verified = 84; every one narrated in §2/§3) | 0 |
| Error codes | 48 | 48 (§5 table = 48; **all 48 also appear in §1–§4 narrative**) | 0 |
| Ladder rungs | 45 | 45 (§2.5 enumerates 1–45 verbatim; each condition restated at its workflow) | 0 |
| Calculations | 37 | 37 (all variant selectors, constants, rounding order and tie-breaks in prose) | 0 |
| Status axes | 19 | 19 (all 19 entity/state_field pairs, both branches of every fork) | 0 |
| Entities / fields | 19 / 180 | 180 field names in backticks | 0 |
| Request-body + output identifiers | 120 | 120 | 0 |
| Query params | 48 | 48 | 0 |
| Write gates / conservation invariants / OCC rules | 5 / 6 / 3 | 5 / 6 / 3 | 0 |

**Contract 1** PASS (180/120/48/1 present, 0 missing). **Contract 2** PASS. **Contract 3** PASS (1,161 §3 backtick tokens scanned; 0 path tokens, 0 bare methods, 0 method+path).

Two accuracy defects found during the Contract-2 audit and fixed: the foster restriction evaluation was written as guarding all three placement operations when the scaffold scopes it to propose + transfer only (activation excluded); and the §4 status-code rule needed an explicit list of the six action endpoints that mint a row and therefore answer 201.

### Friction points left un-adjudicated — 10

1. **Gate 1 scope vs. its condition** (§2.6). A: the freeze gate can only fire where an owning organization is reachable through an animal, so person/foster-home/foster-application/contribution/partner-commitment writes are never frozen. B: the full declared "every POST/PATCH/DELETE" scope applies, resolving the org through any organization-bearing field on the target.
2. **Rung-4 code for a PartnerRescue actor** (§2.11). A: rung 4 emits `ERR_PERSON_NOT_FOUND` for every entity-backed role as declared. B: the backing entity decides via the closed map, so an unresolvable `PartnerRescue` gets `ERR_ORGANIZATION_NOT_FOUND`.
3. **Missing `reason` on a freeze** (§3.1). A: `ERR_VALIDATION` at rung 6 (optional field, absent). B: `ERR_INVALID_STATE` at rung 18 (transition precondition "reason is a non-empty string").
4. **Certificate `EXPIRED` latch** (§3.5). A: any read or write observing the clock past `expires_at` latches. B: only a departure check latches, so an isolated read may still report `VALID`.
5. **Intake-transport destination organization** (§3.6). A: repoint `current_organization_id` to the run's `origin_organization_id`. B: no destination organization is modelled on a run, so arrival leaves it unchanged.
6. **Re-manifesting a stranded animal** (§3.6). A: the existing entry mutates `STRANDED → ASSIGNED` (one row). B: the entry stays `STRANDED` for audit and a fresh `ASSIGNED` row is created (two rows) — as that transition's own side-effect text states.
7. **Species vs. expiry order on transfer-out run start** (§3.7). A: ladder order → `ERR_PARTNER_SPECIES_MISMATCH` (rung 32 above rung 39). B: the transition's own precondition order → `ERR_PARTNER_COMMITMENT_UNAVAILABLE`.
8. **Deposit refund amount** (§3.8). A: the full `alteration_deposit_cents`. B: only the portion actually covered by `adopter_paid_cents`.
9. **Credit restoration allocation on a `FEE_ASSESSED` return** (§3.9). A: proportional across each drawn contribution. B: reverse draw order until exhausted.
10. **Returning a `PARTIALLY_PAID` adoption** (§3.9). A: no transition declared out of `PARTIALLY_PAID`, so the money axis does not move. B: the refund tiers apply from any state where cash was received, so it advances to `REFUNDED_PARTIAL`/`REFUNDED_FULL`.

Both design files were never opened, and no sibling task was read. No worked examples were carried into the prose — every numeric statement is a rule (threshold, rate, boundary inclusivity), not a computed instance.

## Step 5: Generate unit tests — 2026-08-09T06:30:00.000Z

(Launched CONCURRENTLY with Step 6 in a single assistant message — parallel *and* physically isolating, since `test_suite/` did not exist on disk when impl-gen started.)

All done. Final verification passes: 95 tests collect cleanly, every `Design:` tag resolves, every quoted PRD sentence survives a literal grep of `PRD.md`, no `skip`/`xfail`, no scaffold references in emitted code.

### Files & counts

**`test_helpers/`** — `__init__.py`, `types.py`, `api_client.py` (one method per endpoint), `api_errors.py` (48 codes + status map), `assertions.py` (incl. `assert_same_instant` + the six conservation checkers), `factories.py`, `constants.py`, `test_users.py` (per-instance builders for all four entity-backed roles), `fixtures.py`.

**`test_suite/`** — `conftest.py` + 11 test files, **95 tests total**:

| file | tests |
|---|---|
| test_01_registry_defaults.py | 8 |
| test_02_not_found_and_input_validation.py | 9 |
| test_03_intake_stray_hold_and_reclaim.py | 6 |
| test_04_holds_and_custody_gates.py | 7 |
| test_05_foster_pipeline.py | 11 |
| test_06_medical_funding_and_certificates.py | 7 |
| test_07_transport_manifests.py | 11 |
| test_08_transport_relay_and_departures.py | 6 |
| test_09_adoption.py | 15 |
| test_10_outcomes_returns_and_reporting.py | 12 |
| test_11_partner_commitments_and_authentication.py | 3 |

### Coverage

- **Queue A: 18 / 18** difficulty instances translated, each with ≥ 2 tests (36 tests).
- **Queue B: 59 / 59** non-stub corner instances translated, ≥ 1 test each (59 tests).
- **11 `excluded_because:` stubs** not translated; all 11 `difficulty_instance` cross-references verified to resolve to real §1.8 instances.
- **Instances skipped: none.**

### Friction points — how each was dodged

1. **Gate-1 scope** — avoided. The only freeze test writes an animal-scoped resource (a hold on the frozen org's animal), where both readings resolve the same owning org. No test writes a person / foster home / foster application / contribution / partner commitment while an org is frozen.
2. **Rung-4 `PartnerRescue` code** — no instance exercises an unresolvable `PartnerRescue` actor; nothing emitted.
3. **Missing freeze `reason`** — no instance; every freeze-raise supplies a non-empty reason.
4. **Certificate `EXPIRED` latch** — *agreement-by-construction*. `cat_cvi.status == EXPIRED` is only read **after** a departure check has already evaluated that certificate past `expires_at` (the check is what produced `ERR_CVI_EXPIRED`). Reading A (any read latches) and Reading B (only a departure check latches) therefore both yield `EXPIRED`. The companion `dog_cvi.status == VALID` is un-expired, so both readings agree trivially.
5. **Intake-transport arrival destination org** — avoided. No test arrives a run's highest-sequence leg, and no test asserts `current_organization_id` after any arrival.
6. **Re-manifesting a stranded animal** — avoided. The abort cascade tests stop at `STRANDED`; nothing is re-manifested.
7. **Species vs. expiry order on run start** — *agreement-by-construction*. Run 1 violates **only** species (its CAT commitment runs to 2026-07-01, clock 2026-05-05); run 2 violates **only** expiry (DOG commitment, species matches). With exactly one condition failing per run, neither ordering can change the observable code.
8. **Deposit refund amount** — *agreement-by-construction*. The adopter pays the full 22100 target (12500 charge + 9600 deposit) before redemption, so Reading A (full `alteration_deposit_cents`) and Reading B (portion covered by `adopter_paid_cents`) both give 9600.
9. **Credit-restoration allocation** — *agreement-by-construction*. Exactly one contribution supplied the whole 20000-cent sponsorship, so proportional and reverse-draw-order allocations are identical.
10. **Returning a `PARTIALLY_PAID` adoption** — avoided. Both returns that assert `fee_status` start from `PAID`; the conservation-test returns have `adopter_paid_cents == 0` (PRD states neither refunded state is reached under either reading) and assert no `fee_status`.

### Design-index expected values that could not be re-derived (assertion omitted, instance kept)

1. **`compensating_invariant / intake_outcome_count_conservation_across_adoption_return`** asserts `charged == 25000`. The animal is born 2018-01-01 and finalized 2026-06-01 → 3073 elapsed days → `age_months` 102 ≥ 84 → **SENIOR** waiver at 60 %. Under `CREDIT_FIRST` with an empty pool: sponsorship 0, waiver 15000, `adopter_charged_cents` **10000**, not 25000. Omitted; the instance's conservation claims are unaffected.
2. **`validations / legal_hold_blocks_transport_while_medical_hold_does_not`** asserts `reclaim_total_cents == 4500`. Intake `2026-05-01T00:00:00Z` with the clock still at `2026-05-01T00:00:00Z` under `CALENDAR_DAY` touches 1 date → `impound_billable_days` 1 → subtotal 1500 → ×1.0 + 4500 base fee = **6000** (no waiver, `hardship_certified` false). Omitted; the legal/medical asymmetry claims are kept.
3. Not a numeric disagreement but a derivability gap: **`TransportRun.slots_drawn == 0` after the leg-abort cascade** was omitted — PRD §3.7 defines "its `slots_drawn` are returned" solely in terms of the *commitment's* fields and never states that the run's own `slots_drawn` is zeroed. The commitment and organization ledger assertions are kept.

## Step 6: Generate implementation — 2026-08-09T06:30:00.000Z

(Launched CONCURRENTLY with Step 5 in a single assistant message.)

Implementation complete and verified.

### Modules (22 files, 4497 lines)

| module | lines | | module | lines |
|---|---|---|---|---|
| `app.py` | 111 | | `routes/orgs.py` | 136 |
| `auth.py` | 96 | | `routes/animals.py` | 220 |
| `calc.py` | 452 | | `routes/intake.py` | 174 |
| `clock.py` | 182 | | `routes/foster.py` | 420 |
| `derive.py` | 359 | | `routes/medical.py` | 174 |
| `envelope.py` | 42 | | `routes/transport.py` | 493 |
| `errors.py` | 103 | | `routes/adoption.py` | 394 |
| `gates.py` | 161 | | `routes/outcomes.py` | 127 |
| `ids.py` | 54 | | `routes/funding.py` | 165 |
| `routing.py` | 75 | | `services.py` | 197 |
| `store.py` | 92 | | `validation.py` | 270 |

Plus `start.sh` + `requirements.txt`. Authored in 22 bounded Writes — no oversized single write.

### B. Completeness gate
**84/84 matched · MISSING 0 · EXTRA 1** (`GET /static/<path>`, Flask's built-in — expected). Verified programmatically against scaffold `endpoints[]` with path params normalized, booting the app in-process and diffing `app.url_map`.

### C. The two recurring bugs — both adjudicated

**1. Timestamp rendering.** All instant rendering routes through `clock.py` (`canonical` / verbatim / `derive`). Three-case policy, HTTP-verified on a live boot:

- **(a) server-minted** — `created_at`/`updated_at`/`api_request_timestamp`, always 3 fractional digits: `'2026-06-15T09:30:00.000Z'`
- **(b) caller-supplied — echoed byte-verbatim**: sent `'2026-06-15T09:30:00Z'` → `intake_datetime` `'2026-06-15T09:30:00Z'`; sent `'2026-06-15T09:30:00.123Z'` → `issued_at` `'2026-06-15T09:30:00.123Z'`; sent `'2026-06-15T09:30:00+00:00'` → `home_check_passed_at` `'2026-06-15T09:30:00+00:00'`
- **(c) derived — in the source string's style**: `hold_expires_at` `'2026-06-18T09:30:00Z'` (from `intake_datetime`); cert `expires_at` `'2026-07-15T09:30:00.123Z'` (keeps `.123`); `home_check_expires_at` `'2026-12-12T09:30:00+00:00'` (keeps `+00:00`). Clock-stamped instants derive from the clock string: clock `'2026-06-15T09:30:00Z'` → `released_at` `'2026-06-15T09:30:00Z'` — **no `.000Z` drift, no wall-clock leak**.

**2. Enum routing — closed iff-list.** Documented at the head of `validation.py`. `ERR_INVALID_ENUM` routes **exactly**: org `org_type`,`default_methodology`; person `housing_type`; animal `species`,`size_class`,`temperament`, each element of `restriction_housing_types_excluded`; intake `intake_type`,`impound_billing_basis`; hold `hold_type`; foster-app `species_requested`; placement `count_basis`; medical `procedure_type`,`expense_category`; run `run_type`,`purpose`; leg `species_policy`; adoption `credit_application_order`,`refund_basis`,`deposit_basis`; outcome `outcome_type`; contribution `designated_program`,`restriction_category`; commitment `species`; the `decision` field on both decision endpoints; `result` (home-check); `action` (status-change); `reason` (placement-end); `methodology` (report query). **No other field routes here.** Deliberate exclusions, HTTP-verified on both sides: every other list query filter never errors (`?species=FISH` → 200, `total_count` 0); numeric-range failures → `ERR_VALIDATION` (`weight_lb: 0`); format failures → `ERR_VALIDATION` (`state_code: "nyc"`, bad email, bad datetime); wrong JSON type on an enum → `ERR_VALIDATION` at rung 6 (`species: 7`); body FKs → the 2.11 not-found map (`ERR_ORGANIZATION_NOT_FOUND`); wrong-state → `ERR_INVALID_STATE`.

### D. EADDRINUSE
Pre-bind with `SO_REUSEADDR`, 24 × 0.25 s (~6 s) bounded retry, then hard `sys.exit(1)`; served via `make_server(..., fd=sock.fileno())`. **Against a genuinely occupied port** (squatter held it 3 s): server waited and became ready at **2.88 s**, 0 FATAL lines. **12-cycle tight kill/relaunch: 0 start failures, 0 orphans** after the final kill. `start.sh` probes deps with `importlib.util.find_spec`, never `pip` on a warm boot.

### E. The 10 friction adjudications
1. **Gate 1 scope → B.** Full declared scope; org resolved through animal → `animal_id` → `organization_id` → `origin_organization_id`. A leaves partner-commitment/transport writes permanently unable to observe `ERR_RECORDS_FROZEN`; B is a strict superset and strands nothing. *Verified: freeze blocks partner-commitment and transport-run creates.*
2. **Rung-4 PartnerRescue → A** (`ERR_PERSON_NOT_FOUND`). Reachability equal; the literal text states this code twice (§2.1, §2.5 rung 4).
3. **Missing freeze reason → B** (`ERR_INVALID_STATE`, rung 18). A must invent a conditionally-required field, contradicting the endpoint's own `reason?` optionality; B contradicts nothing.
4. **Certificate latch → A** (any read/write latches). B strands the `status=EXPIRED` list filter and any EXPIRED read; A also matches §2.4's general rule.
5. **Intake-transport arrival org → A** (repoint to `origin_organization_id`). B makes the declared side effect unreachable on every input.
6. **Re-manifest → B** (audit row stays `STRANDED`, fresh `ASSIGNED` row). A contradicts the 201-mints-a-row rule and hides the audit row from the status filter.
7. **Species vs expiry on run start → A** (`ERR_PARTNER_SPECIES_MISMATCH`). §2.5 makes the global ladder the sole arbiter; both codes stay reachable either way.
8. **Deposit refund → A** (full `alteration_deposit_cents`). B has no formula anywhere in the PRD; A is stated concretely and strands nothing.
9. **Credit restoration → A** (proportional, last line absorbs the remainder). Totals identical under both; the scaffold already says "a proportional share".
10. **Returning a `PARTIALLY_PAID` adoption → A** (money axis does not move; refund still computed and written). B invents two undeclared transitions; `REFUNDED_*` stay reachable from `PAID`.

### H. Self-verification — 344 HTTP assertions across 6 phases, all passing
Exercised: the **depth-6 leg-abort cascade** (leg→entries→animals→run→partner slots→org roll-up, each hop asserted); **all 5 gates** including the peel sequence LEGAL→MEDICAL→BEHAVIORAL and gate-above-OCC / body-above-gate precedence; **all 3 OCC rules**; dual-variant calcs on **both** branches (CALENDAR_DAY 10 d vs OVERNIGHT 9 d; CREDIT_FIRST 10000/9000/6000 vs WAIVER_FIRST 15000/10000/0 with residual 2000; FLAT vs AGE_SCALED floor 6000; SAC vs ASILOMAR; grouped litter 2 crates vs split-approved per-size); **all 6 conservation invariants**; per-line overhead **801, not 800**; the driver buffer at 59 vs exactly 60 min; the monotone hold latch surviving a clock rewind; the non-monotone home-check lapse/recovery; foster-to-adopt conversion; the full 19-entry not-found map.

Two bugs my own verification caught and I fixed: none in the implementation — both initial red lines were wrong test expectations (an org-balance figure and a masked rung-18 case), confirmed against the PRD before amending. **One thing worth flagging that no test would have caught on its own:** the `ERR_RETURN_WINDOW_CLOSED` case is masked by rung 18 whenever the adoption is already `RETURNED`, so I built a second adoption specifically to reach rung 38 — the code was already correct, but a suite that only re-returns the same adoption would never exercise that rung.

### PRD/SCAFFOLD disagreements and gaps (PRD followed throughout)
- **`Contribution` has no organization FK**, yet §3.9 defines per-organization balances over all contributions. No route exists to scope an undesignated gift to an org, so `unrestricted_balance_cents` / `restricted_balance_cents` are computed as **global** aggregates (identical for every org). Correct for any single-organization fixture; would double-count across two orgs. `open_commitment_slots_total` *is* properly org-scoped (commitments carry `organization_id`).
- Scaffold §1.2 header says "18 status axes across 14 entities"; the body declares 19 state machines. Implemented as declared.
- Scaffold `ManifestEntry` `STRANDED → ASSIGNED` transition text is self-contradictory (a transition whose side effect leaves the row untouched) — this is friction 6, resolved to B.
- Organization roll-ups (`unrestricted_balance_cents`, `restricted_balance_cents`, `open_commitment_slots_total`), `Person.reclaim_history_count`, `Litter.member_count` and `Contribution.available_cents` are **derived on read** per their PRD field definitions ("derived, never stored independently"), so those recomputes bump no `version`. Clock-driven latches (hold, home-check, certificate) likewise bump no `version` — their scaffold `side_effects` declare none.

**Orchestrator isolation + hygiene check (post-hoc):** `grep -rIl "test_suite\|test_helpers\|conftest" implementation/` → empty (impl never saw the tests). `grep -rnE "sqlite|json\.dump|pickle|/tmp/|datetime\.now|utcnow|time\.time\(\)" implementation/ --include=*.py` → empty (in-memory only, logical clock only). `grep -rn "skip\|xfail"` over `test_suite/`+`test_helpers/` → empty. `def test_` count **95** == `Design:` tag count **95** (36 Difficulty + 59 Corner). `ast.parse` over all impl + test files → 0 failures.

## Step 7: Run tests and iterate — 2026-08-09T07:45:00.000Z

Zero source edits confirmed. Here is the final report.

### Summary

**Iterations: 3 sweeps (24 rounds total). Zero fixes, zero deletions.** The suite was clean on the first try; the work was proving it.

**Final sweep (and its repeat), per round:** 8/8 rounds at **95/95 passed, 0 failed, 0 errors, 0 skipped**. Re-run a second time to harden → **16/16 rounds clean**, all collecting a byte-identical 95-test set.

- Tests deleted: **none**.
- Fixes to `test_suite/`: **none**.
- Fixes to `test_helpers/`: **none**.
- Fixes to `implementation/`: **none**. (`find -newermt` confirms no `.py` under `test_suite/`, `test_helpers/`, `workspace/implementation/` was touched.)
- Only file added: `workspace/sweep_serial.sh` (see below).

### The one real problem was operational, not code

Sweeps 1 and 2 each showed exactly one non-passing test per affected round. Discriminated rather than "fixed":

- **Sweep 1** (4-way waves): rounds 1–4 failed on `test_finalizing_auto_declines_every_sibling_application` / `test_the_screening_actor_may_not_also_finalize`; rounds 5–8 clean.
- **Sweep 2** (4-way waves): rounds 6 and 8 failed on a *different* test, `test_naming_an_ineligible_contribution_reports_the_category_mismatch` — **at the same wall-clock second, 06:53:08**, with load 9.7 and **12 concurrent runners (8 belonging to co-tenant tasks 0938/0939/0941/0942)**.
- Zero overlap between sweeps; every failure was connection-level (`RemoteDisconnected`, "could not be restarted"), never an assertion.
- **Direct disproof of a code cause:** an isolated single-round run of `test_09_adoption.py` alone across that exact boundary passed 15/15 in 8.9 s.

Remedy was operational. The host never dropped below 5–8 foreign runners in 20 minutes of monitoring, so the 4-way waves were the tipping factor. Added `workspace/sweep_serial.sh` — the *same 8 rounds run one at a time*, reusing `sweep.sh`'s invocation verbatim (including the required `cd <impl> && bash start.sh` prefix), no inline `pkill`, same `results.N.json` paths. It adds 1 runner instead of 4 and went 8/8 clean twice. `app.py`/`start.sh` untouched; lengthening the bind-retry loop would have made things strictly worse.

### Audit A — the result is real

| Check | Result |
|---|---|
| 8 `results.N.json` parseable, 95 individual rows each | ✅ |
| `passed==95`, `failed==0`, `errors==0`, status set `{'passed'}` | ✅ all 8 (and all 16) |
| Sorted test-name list byte-identical across rounds | ✅ **1 distinct signature across all 16 rounds** |
| `def test_` = collected = `Design:` tags | ✅ 95 / 95 / 95 |
| `skip`/`xfail`/`skipif` | ✅ none |
| `sqlite\|json.dump\|pickle\|/tmp/\|datetime.now\|utcnow\|time.time()` in impl | ✅ none; store is a module-level dict, no seeding |
| Route diff: scaffold `endpoints[]` vs in-process `app.url_map` | ✅ **84/84, 0 missing, `/static/<path>` the only extra** |
| Every asserted response-field name verbatim in PRD | ✅ 160/160 (21 non-matches are local scenario-dict keys) |
| Timestamp assertions semantic, never rendered-string | ✅ 24 `assert_same_instant` calls; zero string comparisons |
| Error assertions pin a single `error_id` | ✅ no `validate_error_is_one_of`, no status-only assertions |
| Design tags | 59 singletons + 18 legitimate pairs (one per difficulty seam's two branches); no triples |

**Positive proof of per-test state reset** — the wipe was made *observable* rather than inferred from the `Killed` line. Running `test_01` + `test_02` with `--isolation none` fails exactly two assertions: `assert 9 == 0` ("a rejected create must not leave an Animal row behind" — it sees test_01's 9 leftover animals) and "an empty database must return an empty data array". The same two files pass 17/17 with per-test-server isolation. The suite's strongest such assertion is `test_the_custody_episode_count_identity_holds_after_the_return`, which asserts a **global** `list_animals(lifecycle_status=IN_CUSTODY)` count of exactly **1** at position ~109 of the run.

### Audit B — the suite is fair (per-friction verdicts)

All 10 `# Adjudication of friction N` comments exist and match the handed-down claims. **No DEPENDS.** Step 7 disagrees with test-gen on one label: it claimed friction 7 was agreement-by-construction; it is actually CLEAN (stronger).

| # | Friction | Impl | Verdict | Re-derivation |
|---|---|---|---|---|
| 1 | Freeze-gate scope for animal-less writes | B | **CLEAN** | The only freeze test blocks a *hold* — reaches an animal, where both readings agree. No animal-less write is ever attempted under freeze. |
| 2 | `PartnerRescue` rung-4 code | A | **CLEAN** | No test ever sends `PartnerRescue` headers (grep: zero uses of `make_partner_rescue_headers`). |
| 3 | Missing freeze `reason` | B | **CLEAN** | The only raise supplies `"cruelty case subpoena"`; the lift omits `reason`, which is outside the friction's scope. |
| 4 | Certificate expiry latch | A | **AGREEMENT** | Cat CVI issued 05-01, 15 d → expires 05-16; clock 05-20T08:00. The failed `depart` runs **first** and is itself a departure check observing the cert past expiry → B latches there too; A latches on the subsequent read. Both → `EXPIRED`. Dog: 30 d → 05-31 > clock → `VALID` both. |
| 5 | INTAKE_TRANSPORT arrival repoint | A | **CLEAN** (doubly) | The only `INTAKE_TRANSPORT` run is aborted pre-start; the only arrivals are on leg 1 of 2, so the final-leg branch never runs. Even if it did, that fixture has **one** org, so repointing to `origin_organization_id` is a no-op — A and B coincide. |
| 6 | Stranded entry on re-manifest | B | **CLEAN** | No test ever re-manifests a stranded animal. |
| 7 | Species vs expiry order on run start | A | **CLEAN** | Test deliberately splits them: run_one = DOG on a CAT commitment expiring 07-01 (not expired, clock 05-05) → rung 32 only; run_two = DOG on a DOG commitment expiring 05-04 (expired) → rung 39 only. The both-fire case is never built. |
| 8 | Deposit refund amount | A | **AGREEMENT** | Kitten born 04-01, clock 06-01 → 61 d → `age_weeks` 8. AGE_SCALED = 1200×(16−8) = **9600**, inside [6000,18000]. CAT base 12500, no waiver → charged 12500. Payment 22100 = 12500+9600 → `PAID`. A → 9600. B → paid−charged = 22100−12500 = **9600**. Identical. |
| 9 | Credit-restoration allocation | A | **AGREEMENT** | Born 2018-01-01 → 06-01-2026 = 3073 d → `age_months` 102 ≥ 84 → SENIOR 60%. CREDIT_FIRST: sponsorship min(25000,20000)=20000; rem 5000; waiver 3000; charged 2000. Return at +20 d → 50% tier: refund 1000, restored 10000. **Exactly one** contribution was drawn, so proportional (10000×20000/20000) = reverse-draw (last=only) = **10000**. |
| 10 | Return from `PARTIALLY_PAID` | A | **CLEAN** | Every return runs from `PAID` (payment exactly clears the target) or from `UNPAID` with `adopter_paid_cents == 0`, where the PRD says both readings coincide. `PARTIALLY_PAID` is never returned from. |

Handed-down items verified: **B** (all three assertions are indeed absent), **C** (rung 18 `status != FINALIZED` does sit above the rung-38 window check, but `test_a_return_after_the_outer_window_is_refused` reaches rung 38 legitimately via a still-`FINALIZED` adoption), and **D** (`unrestricted_balance_cents()`/`restricted_balance_cents()` take no org argument → global; `open_commitment_slots_total(org_id)` is org-scoped — and the PRD genuinely gives `Contribution` no organization FK, so global is a defensible reading, not a defect).

### Audit C — near-miss register (fair only by accident)

Ordered by distance from the edge.

**Distance 1 — one changed value or one reordering flips it to DEPENDS:**

1. `test_one_expired_certificate_blocks_the_whole_interstate_departure` (friction 4). Fair **only** because the `get_health_certificate` status read comes *after* the failed departure. Move that read above the `depart` call and A→`EXPIRED`, B→`VALID`. **The single riskiest test in the suite.**
2. `test_a_return_inside_the_partial_tier_refunds_half_the_cash` (friction 10). Pays exactly 2000 = full charge → `PAID`. Change to 1000 → `PARTIALLY_PAID`, and the asserted `fee_status == "REFUNDED_PARTIAL"` would **fail on this impl** (A keeps `PARTIALLY_PAID`; B gives `REFUNDED_PARTIAL`).
3. `test_fee_assessed_restores_the_tier_share_of_the_sponsorship_credit` (friction 9). One sponsoring gift. Add a second: two 10000 lines with 10000 restored → proportional (5000, 5000) vs reverse-draw (0, 10000). Diverges immediately.
4. `test_flat_and_age_scaled_deposits_diverge_and_redeem_on_proof` (friction 8). Pays the full 22100. Any lesser payment splits A from B.
5. `test_species_mismatch_and_expiry_each_block_a_transfer_out_run_start` (friction 7). Pull `cat_commitment.expires_at` back before the clock and run_one violates both conditions at once.
6. `test_records_freeze_blocks_a_write_and_lifting_it_lets_the_write_through` (friction 1). Swap the blocked write (a hold) for `create_person`/`create_foster_home`/`create_contribution`/`create_partner_commitment` and A→allowed, B→`ERR_RECORDS_FROZEN`.
7. **Item D exposure** (not a friction — PRD silence). Every balance assertion uses a single org holding all contributions. Add one contribution against a second org while keeping the existing `unrestricted_balance_cents` assertion and the global aggregate is exposed.

**Distance 2 — needs two changes:**

8. `test_flat_and_age_scaled_deposits_...`, the `flat` branch: K1's 15000 deposit is never paid *and* never redeemed. Adding a redemption without a payment needs both an added call and an added assertion.
9. `test_aborting_a_departed_leg_strands_its_entries_and_its_animals` (friction 6). Needs one added re-manifest call *plus* an assertion on the original entry's status.
10. `_adopted_then_returned_senior_dog` (friction 10). Returns from `UNPAID`/zero cash and never asserts `fee_status`; would need both a partial payment and a new assertion.
11. The freeze **lift** call omits `reason`. Safe under the PRD's own scoping (the open point covers only `freeze_active: true`), but an implementer who over-generalised Reading A into an unconditionally-required body field would reject it. Low risk.

**Orchestrator independent re-verification:** all 8 `results.N.json` re-parsed → **95 individual rows each**, `passed=95 failed=0`, status value-set exactly `{'passed'}`, sorted-name sha256 `dcda76eaecf7` **identical across all 8**. Route diff re-run comparing **(method, path) pairs** rather than path alone: scaffold 84 pairs, app 85, **0 missing, 1 extra = `GET /static/{P}`**. Worth recording that the path-only form would have compared 73 vs 74 — a method-aware diff is the only one that actually proves completeness here.

## Step 8: Finalize PRD — SKIPPED — 2026-08-09T07:50:00.000Z

Skip condition met exactly: Step 7 exited with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes**. `PRD.md` already determined every behavior the implementation exhibits at every site Step 7 exercised, so there is no `<step_7_diff>` to patch against. No subagent spawned; `PRD_FINALIZED.md` is intentionally absent and Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-09T08:10:00.000Z

The patch is complete. `PRD_COMPLETED.md` is written.

**File deltas:** `PRD.md` 608 lines / 127,278 chars → `PRD_COMPLETED.md` 630 lines / 153,167 chars (+22 lines, +25,889 chars). 55 source lines revised in place, 0 new sections or headings (heading list verified byte-identical), all 10 `> **Open point**` blockquotes removed (blockquote count 10 → 0), ladder still 45 rungs, conservation identities still 6.

**Counts:** 62 changes — 47 ambiguity-pins, 15 mismatch-revisions.

### Per-probe yield
| Probe | Hits | Highest-value finding |
|---|---|---|
| **Q1** declared-but-never-consulted | **11** | `run_type` (RESCUE_LEG vs RELAY) branches nothing; `approved_reason` and `proof_reference` required→discarded; abort/return `reason` discarded; run-level hub codes, `vet_license_number`, `window_days`, hold `reason` inert. Sub-shape hit: the named-contribution category check runs **even when `funding_required` is false**, so names are validated then discarded yet can still refuse the completion. |
| **Q7** version ledger | **10** | **Corrects §2.4 outright**: impl is *one bump per row per request*, never per mutation step. Plus the foster-home asymmetry (propose/activate bump unconditionally; end/cancel/transfer bump only on a `capacity_status` flip) and a zero-animal transfer-out start that bumps the commitment against an unchanged ledger. |
| **Q9** error precedence | **8** | Conditional-required fields sit at rung 8 *above* path resolution; driver-licence + `sequence_no`-uniqueness `ERR_VALIDATION`s sit *below* rung 19; rung 21 fires on any `intake_type`; rung 38 confirmed masked by rung 18 (lead 4 correct). |
| **Q2** universal quantifiers | **7** | Ownership scoping is *not* uniform: `Driver` reads any run and any certificate unscoped; a run with no `partner_commitment_id` is unreadable by every `PartnerRescue`; list `total_count` is post-role-scope. |
| **Q10** timestamps | **6** | Three-policy rendering (server-minted canonical / caller-echoed verbatim / derived-in-source-style, with clock stamps echoing the setter's own bytes) — entirely absent from the PRD. |
| **Q8** unenforced scope/uniqueness | **5** | The replacement leg's `origin_hub_code` == animal's `current_hub_code` is **never checked**; `dam_animal_id` shape unenforced. |
| **Q5** list semantics | **5** | `has_more` formula, empty-string params ignored, no filter ever routes to `ERR_INVALID_ENUM`, null fields never match. |
| **Q4** serializers | **4** | Fixed key set, explicit nulls, derived figures projected *after* every bump. |
| **Q3** derived-status vs gate | **3** | `capacity_status` is latched, not continuously evaluated — a home with both capacities 0 reports `OPEN` forever. |
| **Q6** cascade legs that don't fire | **3** | Run `COMPLETED` tested only on the highest-sequence arrival and defeated by any `ABORTED`/`INVALIDATED` leg; extension silently skipped on non-`STRAY` episodes. |
| **Additional shapes** | **2** | *Stated mechanism does not exist*: organization `state_code` is claimed to "drive whether a transport leg counts as interstate" — nothing reads it; `crosses_state_line` alone decides. *Declared reversible loop one-way in code*: credit restored onto a contribution the outcome cascade already `RELEASED` stays `RELEASED`. |

### The 10 friction points — all pinned, all as reported
1→B (full freeze scope, with the complete gated/ungated map written out) · 2→A (`ERR_PERSON_NOT_FOUND` for `PartnerRescue`) · 3→B (`ERR_INVALID_STATE` at rung 18) · 4→A (any read latches CVI) · 5→A (arrival repoints to `origin_organization_id`) · 6→B (stranded row kept, fresh `ASSIGNED` minted) · 7→A (species beats expiry) · 8→A (full deposit) · 9→A (proportional, last line absorbs the residue) · 10→A (money axis stays put). **No impl-gen claim about the frictions was wrong.**

### Where handed-down claims needed correcting
- **Lead 2 confirmed and extended:** both money roll-ups are global, `open_commitment_slots_total` is org-scoped — and §3.9's defining sums needed revising too, not just §3.1.
- **Lead 6 was already satisfied** — §2.8 pins per-line overhead rounding correctly; no edit was warranted there, only the *weight* rounding order (rounded-then-compared) was unpinned.
- **The one real correction is to the PRD's own §2.4**, which asserts per-mutation-step versioning and cites finalization as the example. The implementation does the opposite everywhere, and the `Adoption` it cites is created at `version` 1 and never re-bumped.

**Orchestrator final verification:** `find workspace/implementation test_suite test_helpers -name '*.py' -newer results.1.json` → **empty**, proving Step 9 edited no code. `diff` of all `^#` headings `PRD.md` vs `PRD_COMPLETED.md` → **identical**, proving no new sections. "Open point" occurrences 10 → **0**. `PRD_FINALIZED.md` correctly absent. All 8 `results.N.json` retained.

---

# PIPELINE COMPLETE

**task_0940_animal_rescue_foster_transport — 95/95 on 16 sweep rounds, 0 deletions, 0 fixes of any kind.** Step 8 skipped; Step 9 carried the whole completeness yield at 62 edits.
