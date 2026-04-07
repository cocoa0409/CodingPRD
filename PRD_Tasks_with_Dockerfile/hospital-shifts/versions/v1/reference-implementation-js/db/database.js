class InMemoryDatabase {
  constructor() {
    this.tables = {
      treatment_plans: [],
      budget_ledgers: [],
      safety_ledgers: [],
      ward_rotations: [],
      procedures: [],
      medical_resources: [],
      resource_certifications: [],
      assignments: [],
      infection_risk_pairings: []
    };
  }

  prepare(sql) {
    return {
      run: (...params) => this._execute(sql, params),
      get: (...params) => this._queryOne(sql, params),
      all: (...params) => this._queryAll(sql, params)
    };
  }

  exec(sql) {

  }

  _execute(sql, params) {
    const match = sql.match(/INSERT INTO (\w+)/i);
    if (match) {
      const table = match[1];
      const values = this._parseInsertValues(sql, params);
      this.tables[table].push(values);
      return { changes: 1 };
    }

    const updateMatch = sql.match(/UPDATE (\w+) SET (.+?) WHERE (.+)/i);
    if (updateMatch) {
      const table = updateMatch[1];
      const setClause = updateMatch[2];
      const whereClause = updateMatch[3];

      const setParamCount = (setClause.match(/\?/g) || []).length;

      const rows = this.tables[table].filter(row =>
        this._matchesWhere(row, whereClause, params, setParamCount)
      );

      rows.forEach(row => {
        this._applySetClause(row, setClause, params);
      });
      return { changes: rows.length };
    }

    const deleteMatch = sql.match(/DELETE FROM (\w+)(?:\s+WHERE (.+))?/i);
    if (deleteMatch) {
      const table = deleteMatch[1];
      const whereClause = deleteMatch[2];

      if (!whereClause) {

        const count = this.tables[table].length;
        this.tables[table] = [];
        return { changes: count };
      }

      const originalLength = this.tables[table].length;
      this.tables[table] = this.tables[table].filter(row =>
        !this._matchesWhere(row, whereClause, params, 0)
      );
      return { changes: originalLength - this.tables[table].length };
    }

    return { changes: 0 };
  }

  _parseInsertValues(sql, params) {
    const columnsMatch = sql.match(/\(([^)]+)\)/);
    const valuesMatch = sql.match(/VALUES\s*\(([^)]+)\)/i);

    if (!columnsMatch || !valuesMatch) return {};

    const columns = columnsMatch[1].split(',').map(c => c.trim());
    const valueParts = valuesMatch[1].split(',').map(v => v.trim());
    const values = {};
    let paramIndex = 0;

    columns.forEach((col, index) => {
      const valuePart = valueParts[index];

      if (valuePart === '?') {

        values[col] = params[paramIndex++];
      } else if (valuePart.startsWith("'") && valuePart.endsWith("'")) {

        values[col] = valuePart.slice(1, -1);
      } else if (!isNaN(valuePart)) {

        values[col] = Number(valuePart);
      } else {

        values[col] = valuePart;
      }
    });

    return values;
  }

  _applySetClause(row, setClause, params) {
    const assignments = setClause.split(',');
    let paramIndex = 0;

    assignments.forEach(assignment => {
      const [column, expression] = assignment.split('=').map(s => s.trim());

      if (expression === '?') {
        row[column] = params[paramIndex++];
      } else if (expression.includes('version + 1')) {
        row.version = (row.version || 0) + 1;
      } else if (expression.includes('+')) {
        const match = expression.match(/(\w+)\s*\+\s*\?/);
        if (match) {
          row[match[1]] = (row[match[1]] || 0) + params[paramIndex++];
        }
      } else if (expression.includes('CASE WHEN')) {

        const match = expression.match(/WHEN\s+(\w+)\s*-\s*\?/);
        if (match) {
          const col = match[1];
          const decrementValue = params[paramIndex++];
          paramIndex++;
          row[col] = Math.max(0, (row[col] || 0) - decrementValue);
        }
      } else {

        if (/^-?\d+(?:\.\d+)?$/.test(expression)) {
          row[column] = parseFloat(expression);
        } else {

          const strMatch = expression.match(/^['\"]([\s\S]*)['\"]$/);
          if (strMatch) {
            row[column] = strMatch[1];
          }
        }
      }
    });

    return paramIndex;
  }

  _evaluateWhere(row, whereClause, params) {

    const setMatch = whereClause.match(/SET (.+?) WHERE/i);
    let whereParamOffset = 0;

    if (setMatch) {

      const setClause = setMatch[1];
      whereParamOffset = (setClause.match(/\?/g) || []).length;
    }

    return this._matchesWhere(row, whereClause, params, whereParamOffset);
  }

  _queryOne(sql, params) {
    const results = this._queryAll(sql, params);
    return results.length > 0 ? results[0] : undefined;
  }

  _queryAll(sql, params) {
    const tableMatch = sql.match(/FROM (\w+)/i);
    if (!tableMatch) return [];

    const table = tableMatch[1];
    let results = [...(this.tables[table] || [])];

    const whereMatch = sql.match(/WHERE ([\s\S]+?)(?:ORDER BY|LIMIT|$)/i);
    if (whereMatch) {
      results = results.filter(row => this._matchesWhere(row, whereMatch[1], params));
    }

    if (sql.includes('JOIN')) {
      results = this._handleJoin(sql, results, params);
    }

    if (sql.includes('COUNT(*)')) {
      return [{ count: results.length }];
    }

    const orderMatch = sql.match(/ORDER BY ((?:\w+\.)?\w+)(?:\s*,\s*((?:\w+\.)?\w+))?\s+(ASC|DESC)?/i);
    if (orderMatch) {
      const field1 = orderMatch[1].includes('.') ? orderMatch[1].split('.')[1] : orderMatch[1];
      const field2 = orderMatch[2] ? (orderMatch[2].includes('.') ? orderMatch[2].split('.')[1] : orderMatch[2]) : null;
      const direction = (orderMatch[3] || 'ASC').toUpperCase();

      results.sort((a, b) => {

        const aVal1 = a[field1];
        const bVal1 = b[field1];
        const comparison1 = aVal1 < bVal1 ? -1 : aVal1 > bVal1 ? 1 : 0;

        if (comparison1 === 0 && field2) {
          const aVal2 = a[field2];
          const bVal2 = b[field2];
          const comparison2 = aVal2 < bVal2 ? -1 : aVal2 > bVal2 ? 1 : 0;
          return direction === 'ASC' ? comparison2 : -comparison2;
        }

        return direction === 'ASC' ? comparison1 : -comparison1;
      });
    }

    const limitMatch = sql.match(/LIMIT (\d+)/i);
    const offsetMatch = sql.match(/OFFSET (\d+)/i);

    if (offsetMatch) {
      const offset = parseInt(offsetMatch[1]);
      results = results.slice(offset);
    }

    if (limitMatch) {
      const limit = parseInt(limitMatch[1]);
      results = results.slice(0, limit);
    }

    return results;
  }

  _handleJoin(sql, baseResults, params) {

    if (sql.includes('JOIN procedures')) {
      return baseResults
        .map(assignment => {
          const procedure = this.tables.procedures.find(p => p.id === assignment.procedure_id);
          if (!procedure) return null;

          const {id: proc_id, ...procedureFields} = procedure;
          return { ...assignment, ...procedureFields };
        })
        .filter(row => row !== null);
    }
    return baseResults;
  }

  _matchesWhere(row, whereClause, params, paramOffset = 0) {

    whereClause = whereClause.replace(/\s+/g, ' ').trim();

    if (whereClause.startsWith('(') && whereClause.endsWith(')')) {
      return this._matchesWhere(row, whereClause.substring(1, whereClause.length - 1), params, paramOffset);
    }

    if (/\s+OR\s+/i.test(whereClause)) {
      const conditions = this._hasNestedParens(whereClause)
        ? this._splitOnOperator(whereClause, 'OR')
        : whereClause.split(/\s+OR\s+/i);

      if (conditions && conditions.length > 1) {
        let offset = paramOffset;
        return conditions.some(cond => {
          const result = this._matchesWhere(row, cond.trim(), params, offset);
          const paramCount = (cond.match(/\?/g) || []).length;
          offset += paramCount;
          return result;
        });
      }
    }

    if (/\s+AND\s+/i.test(whereClause)) {
      const conditions = this._hasNestedParens(whereClause)
        ? this._splitOnOperator(whereClause, 'AND')
        : whereClause.split(/\s+AND\s+/i);

      if (conditions && conditions.length > 1) {
        let offset = paramOffset;
        return conditions.every(cond => {
          const result = this._matchesWhere(row, cond.trim(), params, offset);
          const paramCount = (cond.match(/\?/g) || []).length;
          offset += paramCount;
          return result;
        });
      }
    }

    if (whereClause.includes(' IN (')) {
      const match = whereClause.match(/(?:\w+\.)?(\w+)\s+IN\s+\(([^)]+)\)/i);
      if (match) {
        const field = match[1];
        const inClause = match[2].trim();

        if (inClause.includes('?')) {
          const paramCount = (inClause.match(/\?/g) || []).length;
          const values = [];
          for (let i = 0; i < paramCount; i++) {
            if (paramOffset + i < params.length) {
              values.push(params[paramOffset + i]);
            }
          }
          return values.includes(row[field]);
        } else {

          const values = inClause.split(',').map(v => v.trim().replace(/['"]/g, ''));
          return values.includes(String(row[field]));
        }
      }
    }

    if (whereClause.includes('!=') || whereClause.includes('<>')) {
      const match = whereClause.match(/(?:\w+\.)?(\w+)\s*(?:!=|<>)\s*['"]?([^'"?\s]+)['"]?/);
      if (match) {
        return row[match[1]] !== match[2];
      }
    }

    const eqMatch = whereClause.match(/(?:\w+\.)?(\w+)\s*=\s*\?/);
    if (eqMatch) {
      if (params.length > paramOffset) {
        return row[eqMatch[1]] === params[paramOffset];
      }
      return false;
    }

    const eqLiteralMatch = whereClause.match(/(?:\w+\.)?(\w+)\s*=\s*['"]([^'"]+)['"]/);
    if (eqLiteralMatch) {
      return row[eqLiteralMatch[1]] === eqLiteralMatch[2];
    }

    return true;
  }

  _hasNestedParens(str) {

    return (str.match(/\(/g) || []).length > (str.match(/\bIN\s*\(/gi) || []).length;
  }

  _splitOnOperator(str, operator) {

    const parts = [];
    let current = '';
    let parenDepth = 0;
    let i = 0;
    const opRegex = new RegExp(`^\\s+${operator}\\s+`, 'i');

    while (i < str.length) {
      const char = str[i];

      if (char === '(') {
        parenDepth++;
        current += char;
        i++;
      } else if (char === ')') {
        parenDepth--;
        current += char;
        i++;
      } else if (parenDepth === 0) {

        const match = str.substring(i).match(opRegex);
        if (match) {
          parts.push(current.trim());
          current = '';
          i += match[0].length;
        } else {
          current += char;
          i++;
        }
      } else {
        current += char;
        i++;
      }
    }

    if (current.trim()) {
      parts.push(current.trim());
    }

    return parts.length > 1 ? parts : null;
  }
}

const db = new InMemoryDatabase();
module.exports = db;
