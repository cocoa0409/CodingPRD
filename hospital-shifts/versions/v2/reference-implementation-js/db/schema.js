function initializeSchema(db) {
  db.exec(`
    CREATE TABLE treatment_plans (
      id TEXT PRIMARY KEY,
      plan_name TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'PLANNING',
      total_budget REAL NOT NULL,
      cost_balance REAL NOT NULL,
      patient_safety_score INTEGER NOT NULL DEFAULT 0,
      policies TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE budget_ledgers (
      plan_id TEXT PRIMARY KEY,
      provisional_debits REAL NOT NULL DEFAULT 0.0,
      finalized_debits REAL NOT NULL DEFAULT 0.0,
      FOREIGN KEY (plan_id) REFERENCES treatment_plans(id)
    );

    CREATE TABLE safety_ledgers (
      plan_id TEXT PRIMARY KEY,
      safety_score INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY (plan_id) REFERENCES treatment_plans(id)
    );

    CREATE TABLE ward_rotations (
      id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      name TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'PLANNING',
      start_minute INTEGER NOT NULL,
      end_minute INTEGER NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY (plan_id) REFERENCES treatment_plans(id)
    );

    CREATE TABLE procedures (
      id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      rotation_id TEXT NOT NULL,
      procedure_type TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'PENDING',
      required_certification TEXT NOT NULL DEFAULT 'NONE',
      start_minute INTEGER NOT NULL,
      end_minute INTEGER NOT NULL,
      duration_minutes INTEGER NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY (plan_id) REFERENCES treatment_plans(id),
      FOREIGN KEY (rotation_id) REFERENCES ward_rotations(id)
    );

    CREATE TABLE medical_resources (
      id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      resource_name TEXT NOT NULL,
      resource_model TEXT NOT NULL,
      operating_cost_per_minute REAL NOT NULL,
      maintenance_threshold_override INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY (plan_id) REFERENCES treatment_plans(id)
    );

    CREATE TABLE resource_certifications (
      id TEXT PRIMARY KEY,
      resource_id TEXT NOT NULL,
      name TEXT NOT NULL,
      applied_date TEXT NOT NULL,
      FOREIGN KEY (resource_id) REFERENCES medical_resources(id)
    );

    CREATE TABLE assignments (
      id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      procedure_id TEXT NOT NULL,
      resource_id TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'PENDING_SCHEDULE',
      override_protocol_check INTEGER NOT NULL DEFAULT 0,
      protocol_override_penalty_applied INTEGER NOT NULL DEFAULT 0,
      is_high_biorisk INTEGER NOT NULL DEFAULT 0,
      provisional_cost REAL NOT NULL,
      final_cost REAL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY (plan_id) REFERENCES treatment_plans(id),
      FOREIGN KEY (procedure_id) REFERENCES procedures(id),
      FOREIGN KEY (resource_id) REFERENCES medical_resources(id)
    );

    CREATE TABLE infection_risk_pairings (
      id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      resource_id_1 TEXT NOT NULL,
      resource_id_2 TEXT NOT NULL,
      reason TEXT,
      quarantine_until_minute INTEGER,
      created_at TEXT NOT NULL,
      FOREIGN KEY (plan_id) REFERENCES treatment_plans(id),
      FOREIGN KEY (resource_id_1) REFERENCES medical_resources(id),
      FOREIGN KEY (resource_id_2) REFERENCES medical_resources(id)
    );

    CREATE TABLE maintenance_events (
      id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      resource_id TEXT NOT NULL,
      at_minute INTEGER NOT NULL,
      created_at TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY (plan_id) REFERENCES treatment_plans(id),
      FOREIGN KEY (resource_id) REFERENCES medical_resources(id)
    );

    CREATE TABLE resource_holds (
      id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      resource_id TEXT NOT NULL,
      start_minute INTEGER NOT NULL,
      end_minute INTEGER NOT NULL,
      reason TEXT,
      status TEXT NOT NULL DEFAULT 'ACTIVE',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY (plan_id) REFERENCES treatment_plans(id),
      FOREIGN KEY (resource_id) REFERENCES medical_resources(id)
    );

    CREATE TABLE override_authorizations (
      id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      assignment_id TEXT NOT NULL,
      authorized_by_user_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY (plan_id) REFERENCES treatment_plans(id),
      FOREIGN KEY (assignment_id) REFERENCES assignments(id)
    );
  `);
}

module.exports = initializeSchema;
