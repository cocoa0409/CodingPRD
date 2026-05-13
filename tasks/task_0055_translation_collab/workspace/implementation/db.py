"""In-memory data store: dictionaries keyed by id, plus index helpers."""
from __future__ import annotations

import uuid
from typing import Dict, List


class Store:
    def __init__(self) -> None:
        self.clients: Dict[str, dict] = {}
        self.translators: Dict[str, dict] = {}
        self.projects: Dict[str, dict] = {}
        self.project_templates: Dict[str, dict] = {}
        self.documents: Dict[str, dict] = {}
        self.segments: Dict[str, dict] = {}
        self.assignments: Dict[str, dict] = {}
        self.terminology: Dict[str, dict] = {}
        self.quality_scores: Dict[str, dict] = {}
        self.audit_entries: List[dict] = []  # append-only list, plus dict by id
        self.audit_by_id: Dict[str, dict] = {}
        self.external_sync_records: List[dict] = []
        self.sync_by_id: Dict[str, dict] = {}

    def reset(self) -> None:
        self.__init__()


def new_id() -> str:
    return str(uuid.uuid4())


store = Store()
