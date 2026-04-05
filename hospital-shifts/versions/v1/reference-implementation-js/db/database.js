// In-memory database using JavaScript objects
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
    // Schema initialization - no-op for in-memory JS objects
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

      // Count params in SET clause to know where WHERE params start
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
        // DELETE without WHERE - clear entire table
        const count = this.tables[table].length;
        this.tables[table] = [];
        return { changes: count };
      }

      // DELETE with WHERE clause
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
        // It's a parameter
        values[col] = params[paramIndex++];
      } else if (valuePart.startsWith("'") && valuePart.endsWith("'")) {
        // It's a string literal
        values[col] = valuePart.slice(1, -1);
      } else if (!isNaN(valuePart)) {
        // It's a number literal
        values[col] = Number(valuePart);
      } else {
        // Try to evaluate it (for edge cases)
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
        // Handle CASE WHEN for decrement with floor at 0
        const match = expression.match(/WHEN\s+(\w+)\s*-\s*\?/);
        if (match) {
          const col = match[1];
          const decrementValue = params[paramIndex++];
          paramIndex++; // Skip duplicate param
          row[col] = Math.max(0, (row[col] || 0) - decrementValue);
        }
      } else {
        // Handle literal assignments like 0, 0.0, numbers, or quoted strings
        // Numeric literal
        if (/^-?\d+(?:\.\d+)?$/.test(expression)) {
          row[column] = parseFloat(expression);
        } else {
          // Quoted string literal 'VALUE' or "VALUE"
          const strMatch = expression.match(/^['\"]([\s\S]*)['\"]$/);
          if (strMatch) {
            row[column] = strMatch[1];
          }
        }
      }
    });

    // Handle WHERE clause params
    return paramIndex;
  }

  _evaluateWhere(row, whereClause, params) {
    // Count how many parameters are in the SET clause to know WHERE params start
    const setMatch = whereClause.match(/SET (.+?) WHERE/i);
    let whereParamOffset = 0;

    if (setMatch) {
      // This shouldn't happen - whereClause should only be the WHERE part
      // But just in case, skip SET params
      const setClause = setMatch[1];
      whereParamOffset = (setClause.match(/\?/g) || []).length;
    }

    // Use the generic matcher
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

    // Handle WHERE - use [\s\S] to match any character including newlines
    const whereMatch = sql.match(/WHERE ([\s\S]+?)(?:ORDER BY|LIMIT|$)/i);
    if (whereMatch) {
      results = results.filter(row => this._matchesWhere(row, whereMatch[1], params));
    }

    // Handle JOINs
    if (sql.includes('JOIN')) {
      results = this._handleJoin(sql, results, params);
    }

    // Handle COUNT
    if (sql.includes('COUNT(*)')) {
      return [{ count: results.length }];
    }

    // Handle ORDER BY - support both simple fields and table.field notation
    const orderMatch = sql.match(/ORDER BY ((?:\w+\.)?\w+)(?:\s*,\s*((?:\w+\.)?\w+))?\s+(ASC|DESC)?/i);
    if (orderMatch) {
      const field1 = orderMatch[1].includes('.') ? orderMatch[1].split('.')[1] : orderMatch[1];
      const field2 = orderMatch[2] ? (orderMatch[2].includes('.') ? orderMatch[2].split('.')[1] : orderMatch[2]) : null;
      const direction = (orderMatch[3] || 'ASC').toUpperCase();
      
      results.sort((a, b) => {
        // Primary sort by first field
        const aVal1 = a[field1];
        const bVal1 = b[field1];
        const comparison1 = aVal1 < bVal1 ? -1 : aVal1 > bVal1 ? 1 : 0;
        
        // If equal and secondary field exists, sort by it
        if (comparison1 === 0 && field2) {
          const aVal2 = a[field2];
          const bVal2 = b[field2];
          const comparison2 = aVal2 < bVal2 ? -1 : aVal2 > bVal2 ? 1 : 0;
          return direction === 'ASC' ? comparison2 : -comparison2;
        }
        
        return direction === 'ASC' ? comparison1 : -comparison1;
      });
    }

    // Handle LIMIT and OFFSET
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
    // Simple JOIN implementation for assignments with procedures
    if (sql.includes('JOIN procedures')) {
      return baseResults
        .map(assignment => {
          const procedure = this.tables.procedures.find(p => p.id === assignment.procedure_id);
          if (!procedure) return null; // No match for INNER JOIN
          // Don't overwrite assignment fields - only add procedure-specific fields
          const {id: proc_id, ...procedureFields} = procedure;
          return { ...assignment, ...procedureFields };
        })
        .filter(row => row !== null); // Remove non-matches
    }
    return baseResults;
  }

  _matchesWhere(row, whereClause, params, paramOffset = 0) {
    // Normalize whitespace - replace all whitespace sequences with single spaces
    whereClause = whereClause.replace(/\s+/g, ' ').trim();

    // Handle outer parentheses - remove and evaluate the inner expression
    if (whereClause.startsWith('(') && whereClause.endsWith(')')) {
      return this._matchesWhere(row, whereClause.substring(1, whereClause.length - 1), params, paramOffset);
    }

    // Try splitting on OR first (lower precedence)
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

    // Then try splitting on AND (higher precedence)
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

    // Handle IN clause
    if (whereClause.includes(' IN (')) {
      const match = whereClause.match(/(?:\w+\.)?(\w+)\s+IN\s+\(([^)]+)\)/i);
      if (match) {
        const field = match[1];
        const inClause = match[2].trim();

        // Check if it's a parameterized IN clause (contains ?)
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
          // Literal values
          const values = inClause.split(',').map(v => v.trim().replace(/['"]/g, ''));
          return values.includes(String(row[field]));
        }
      }
    }

    // Handle inequality
    if (whereClause.includes('!=') || whereClause.includes('<>')) {
      const match = whereClause.match(/(?:\w+\.)?(\w+)\s*(?:!=|<>)\s*['"]?([^'"?\s]+)['"]?/);
      if (match) {
        return row[match[1]] !== match[2];
      }
    }

    // Simple equality with parameter
    const eqMatch = whereClause.match(/(?:\w+\.)?(\w+)\s*=\s*\?/);
    if (eqMatch) {
      if (params.length > paramOffset) {
        return row[eqMatch[1]] === params[paramOffset];
      }
      return false;
    }

    // Equality with literal
    const eqLiteralMatch = whereClause.match(/(?:\w+\.)?(\w+)\s*=\s*['"]([^'"]+)['"]/);
    if (eqLiteralMatch) {
      return row[eqLiteralMatch[1]] === eqLiteralMatch[2];
    }

    return true;
  }

  _hasNestedParens(str) {
    // Check if string has parentheses that would complicate simple split
    return (str.match(/\(/g) || []).length > (str.match(/\bIN\s*\(/gi) || []).length;
  }

  _splitOnOperator(str, operator) {
    // Split on specific operator (AND or OR) that's outside parentheses
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
        // Check for operator outside parentheses
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
