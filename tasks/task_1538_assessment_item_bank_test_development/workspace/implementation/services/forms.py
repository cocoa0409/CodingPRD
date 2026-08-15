"""Form assembly, exposure accounting, and the compromise cascade (PRD §3.6/§3.7)."""
from db import db
from errors import (
    raise_error,
    ERR_BLUEPRINT_NOT_LOCKED,
    ERR_BLUEPRINT_MISMATCH,
    ERR_SLOT_ITEM_NOT_OPERATIONAL,
    ERR_SLOT_ITEM_INSECURE,
    ERR_DUPLICATE_ITEM_ON_FORM,
    ERR_DOK_OUT_OF_RANGE,
    ERR_WOULD_OVER_EXPOSE,
)
from services.common import touch
from services.review import cascade_item_terminal_variants
from util import program_clock_iso

ACTIVE_FORM_STATUSES = ("ASSEMBLED", "EQUATED", "PUBLISHED")


def retire_item(item, program, reason):
    """Shared retirement side effects (PRD §3.5)."""
    item["status"] = "RETIRED"
    item["retired_at"] = program_clock_iso(program)
    item["retirement_reason"] = reason
    item["security_posture"] = "UNSECURED"
    cascade_item_terminal_variants(item)
    touch(item)


def assemble_form(form, blueprint, program):
    """ASSEMBLING -> ASSEMBLED. All preconditions are validated before any mutation;
    the exposure guard rolls the whole assembly back on would-over-exposure."""
    if blueprint["status"] != "LOCKED":
        raise_error(ERR_BLUEPRINT_NOT_LOCKED, "blueprint must be LOCKED to assemble")

    slots = [s for s in db["form_item_slots"].values() if s["form_id"] == form["id"]]
    sections = blueprint["sections"]

    # Section slot counts must equal blueprinted item_count per section.
    for i, section in enumerate(sections):
        count = sum(1 for s in slots if s["section_index"] == i)
        if count != section["item_count"]:
            raise_error(
                ERR_BLUEPRINT_MISMATCH,
                f"section {i} holds {count} slots, blueprint requires {section['item_count']}",
            )
    extra = [s for s in slots if s["section_index"] < 0 or s["section_index"] >= len(sections)]
    if extra:
        raise_error(ERR_BLUEPRINT_MISMATCH, "slot section_index outside blueprint sections")

    items = []
    for s in slots:
        item = db["items"].get(s["item_id"])
        if item is None or item["status"] != "OPERATIONAL":
            raise_error(ERR_SLOT_ITEM_NOT_OPERATIONAL, f"slot item {s['item_id']} is not OPERATIONAL")
        items.append(item)
    for item in items:
        if item["security_posture"] not in ("SECURED", "EXPOSED"):
            raise_error(ERR_SLOT_ITEM_INSECURE, f"slot item {item['id']} is not SECURED/EXPOSED")
    seen = set()
    for item in items:
        if item["id"] in seen:
            raise_error(ERR_DUPLICATE_ITEM_ON_FORM, f"item {item['id']} appears more than once on the form")
        seen.add(item["id"])

    # Depth-of-knowledge balance per section (bounds inclusive on both ends).
    for i, section in enumerate(sections):
        dok_sum = 0
        for s in slots:
            if s["section_index"] != i:
                continue
            item = db["items"][s["item_id"]]
            standard = db["content_standards"].get(item["primary_standard_id"])
            dok = standard["depth_of_knowledge"] if standard else 0
            dok_sum += dok
        if dok_sum < section["dok_min"] or dok_sum > section["dok_max"]:
            raise_error(
                ERR_DOK_OUT_OF_RANGE,
                f"section {i} DOK sum {dok_sum} outside [{section['dok_min']}, {section['dok_max']}]",
            )

    # Exposure guard: count + 1 must be <= cap for every slotted item.
    for item in items:
        if item["operational_exposure_count"] + 1 > item["exposure_cap"]:
            raise_error(
                ERR_WOULD_OVER_EXPOSE,
                f"item {item['id']} would exceed its exposure cap",
            )

    # Commit.
    form["status"] = "ASSEMBLED"
    form["assembled_at"] = program_clock_iso(program)
    touch(form)
    for item in items:
        item["operational_exposure_count"] += 1
        if item["security_posture"] == "SECURED":
            item["security_posture"] = "EXPOSED"
        touch(item)
        if item["operational_exposure_count"] >= item["exposure_cap"]:
            retire_item(item, program, "OVER_EXPOSED")


def mark_compromised(item, program):
    """EXPOSED -> COMPROMISED with the full rework cascade (PRD §3.7)."""
    item["security_posture"] = "COMPROMISED"

    affected_form_ids = []
    for slot in list(db["form_item_slots"].values()):
        if slot["item_id"] != item["id"]:
            continue
        form = db["test_forms"].get(slot["form_id"])
        if form is None or form["status"] == "ARCHIVED":
            continue
        del db["form_item_slots"][slot["id"]]
        if form["id"] not in affected_form_ids:
            affected_form_ids.append(form["id"])

    for form_id in affected_form_ids:
        form = db["test_forms"][form_id]
        if form["status"] in ("ASSEMBLED", "EQUATED"):
            was_equated = form["status"] == "EQUATED"
            form["status"] = "ASSEMBLING"
            touch(form)
            if was_equated:
                for link in list(db["equating_links"].values()):
                    if link["target_form_id"] == form_id:
                        del db["equating_links"][link["id"]]
            # Compensation: every still-slotted item loses the exposure this form contributed.
            remaining_item_ids = {
                s["item_id"] for s in db["form_item_slots"].values() if s["form_id"] == form_id
            }
            for other_id in remaining_item_ids:
                other = db["items"].get(other_id)
                if other is not None and other["operational_exposure_count"] > 0:
                    other["operational_exposure_count"] -= 1
                    touch(other)
        else:
            touch(form)

    item["operational_exposure_count"] = 0
    touch(item)
